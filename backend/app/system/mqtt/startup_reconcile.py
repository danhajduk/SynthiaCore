from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from .acl_compiler import MqttAclCompiler
from .apply_pipeline import MqttApplyPipeline
from .authority_audit import MqttAuthorityAuditStore
from .config_renderer import MqttBrokerConfigRenderer, MqttBrokerRenderInput, MqttListenerSpec
from .credential_store import MqttCredentialStore
from .integration_models import MqttBootstrapAnnouncement, MqttSetupStateUpdate
from .integration_state import MqttIntegrationStateStore


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class StartupReconcileResult:
    ok: bool
    status: str
    setup_status: str
    runtime_state: str
    error: str | None = None


class EmbeddedMqttStartupReconciler:
    _SYSTEM_PRINCIPAL_IDS: tuple[str, ...] = (
        "core.scheduler",
        "core.supervisor",
        "core.telemetry",
        "core.runtime",
        "core.bootstrap",
    )

    def __init__(
        self,
        *,
        state_store: MqttIntegrationStateStore,
        acl_compiler: MqttAclCompiler,
        config_renderer: MqttBrokerConfigRenderer,
        apply_pipeline: MqttApplyPipeline,
        audit_store: MqttAuthorityAuditStore,
        credential_store: MqttCredentialStore,
        mqtt_manager,
    ) -> None:
        self._state_store = state_store
        self._acl_compiler = acl_compiler
        self._renderer = config_renderer
        self._pipeline = apply_pipeline
        self._audit = audit_store
        self._credential_store = credential_store
        self._mqtt = mqtt_manager
        self._bootstrap_attempts = 0
        self._bootstrap_successes = 0
        self._bootstrap_last_attempt_at: str | None = None
        self._bootstrap_last_success_at: str | None = None
        self._bootstrap_last_error: str | None = None
        self._last_reconcile_at: str | None = None
        self._last_reconcile_reason: str | None = None
        self._last_reconcile_status: str = "unknown"
        self._last_reconcile_error: str | None = None
        self._last_runtime_state: str = "unknown"

    async def reconcile_startup(self) -> StartupReconcileResult:
        return await self.reconcile_authority(reason="startup")

    async def reconcile_authority(
        self,
        *,
        reason: str,
        update_setup_state: bool = True,
        publish_bootstrap: bool = True,
    ) -> StartupReconcileResult:
        await self._ensure_system_principals()
        state = await self._state_store.get_state()
        try:
            acl = self._acl_compiler.compile(state)
            rendered = self._renderer.render(
                MqttBrokerRenderInput(
                    provider="embedded_mosquitto",
                    acl_file=os.path.join(self._pipeline._live_dir, "acl_compiled.conf"),
                    password_file=os.path.join(self._pipeline._live_dir, "passwords.conf"),
                    data_dir=os.path.join(os.getcwd(), "var", "mqtt_runtime", "data"),
                    log_dir=os.path.join(os.getcwd(), "var", "mqtt_runtime", "logs"),
                    listeners=[
                        MqttListenerSpec(name="main", enabled=True, port=1883),
                        MqttListenerSpec(name="bootstrap", enabled=True, port=1884, allow_anonymous=True),
                    ],
                )
            )
            artifacts = dict(rendered.files)
            artifacts["acl_compiled.conf"] = acl.acl_text
            artifacts["passwords.conf"] = self._credential_store.render_password_file(state)
            apply_result = await self._pipeline.apply(artifacts)
            authority_ready = bool(apply_result.ok and apply_result.runtime.healthy)
            activated_addons: list[str] = []
            if authority_ready:
                activated_addons = await self._activate_ready_addon_principals(reason=reason)
            setup_status = "ready" if authority_ready else "degraded"
            if update_setup_state:
                next_setup = MqttSetupStateUpdate(
                    requires_setup=state.requires_setup,
                    setup_complete=authority_ready,
                    setup_status=setup_status,
                    broker_mode=state.broker_mode,
                    direct_mqtt_supported=state.direct_mqtt_supported,
                    setup_error=(None if authority_ready else (apply_result.error or "reconcile_failed")),
                    authority_mode="embedded_platform",
                    authority_ready=authority_ready,
                )
                await self._state_store.update_setup_state(next_setup)
                setup_status = next_setup.setup_status
            if authority_ready and publish_bootstrap:
                await self.ensure_bootstrap_published()
            await self._audit.append_event(
                event_type="mqtt_startup_reconcile",
                status=("ok" if authority_ready else "degraded"),
                message=None if authority_ready else (apply_result.error or "reconcile_failed"),
                payload={
                    "reason": reason,
                    "runtime_state": apply_result.runtime.state,
                    "runtime_healthy": apply_result.runtime.healthy,
                    "activated_addons": activated_addons,
                },
            )
            result = StartupReconcileResult(
                ok=authority_ready,
                status=("ok" if authority_ready else "degraded"),
                setup_status=setup_status,
                runtime_state=apply_result.runtime.state,
                error=(None if authority_ready else apply_result.error),
            )
            self._record_reconcile_outcome(reason=reason, result=result)
            return result
        except Exception as exc:
            await self._audit.append_event(
                event_type="mqtt_startup_reconcile",
                status="error",
                message=type(exc).__name__,
                payload={"detail": str(exc), "reason": reason},
            )
            result = StartupReconcileResult(False, "error", "degraded", "unknown", error=type(exc).__name__)
            self._record_reconcile_outcome(reason=reason, result=result)
            return result

    async def ensure_bootstrap_published(self, *, force: bool = False) -> bool:
        if self._bootstrap_successes > 0 and not force:
            return True
        runtime_status = await self._pipeline._runtime.get_status()
        if not bool(getattr(runtime_status, "healthy", False)):
            self._bootstrap_last_error = "runtime_not_healthy_for_bootstrap_publish"
            return False
        return await self._publish_bootstrap()

    def bootstrap_status(self) -> dict[str, object]:
        return {
            "attempts": self._bootstrap_attempts,
            "successes": self._bootstrap_successes,
            "last_attempt_at": self._bootstrap_last_attempt_at,
            "last_success_at": self._bootstrap_last_success_at,
            "last_error": self._bootstrap_last_error,
            "published": self._bootstrap_successes > 0,
        }

    def reconciliation_status(self) -> dict[str, object]:
        return {
            "last_reconcile_at": self._last_reconcile_at,
            "last_reconcile_reason": self._last_reconcile_reason,
            "last_reconcile_status": self._last_reconcile_status,
            "last_reconcile_error": self._last_reconcile_error,
            "last_runtime_state": self._last_runtime_state,
        }

    def live_dir(self) -> str:
        return str(self._pipeline._live_dir)

    async def _publish_bootstrap(self) -> bool:
        self._bootstrap_attempts += 1
        self._bootstrap_last_attempt_at = _utcnow_iso()
        core_id = "synthia-core"
        core_name = "Synthia Core"
        core_version = str(os.getenv("SYNTHIA_CORE_VERSION", "0.1.0"))
        api_base = "http://127.0.0.1:9001/api"
        mqtt_status = {}
        status_fn = getattr(self._mqtt, "status", None)
        if callable(status_fn):
            try:
                mqtt_status = await status_fn()
            except Exception:
                mqtt_status = {}
        payload = MqttBootstrapAnnouncement(
            core_id=core_id,
            core_name=core_name,
            core_version=core_version,
            api_base=api_base,
            mqtt_host=(str(mqtt_status.get("host")) if mqtt_status and mqtt_status.get("host") else None),
            mqtt_port=(int(mqtt_status.get("port")) if mqtt_status and mqtt_status.get("port") is not None else None),
            onboarding_endpoints={
                "register": "/api/system/mqtt/registrations/approve",
                "setup_state": "/api/system/mqtt/setup-state",
            },
            onboarding_mode="api",
        ).model_dump(mode="json")
        bootstrap_publish = await self._mqtt.publish("synthia/bootstrap/core", payload, retain=True, qos=1)
        info_publish = await self._mqtt.publish("synthia/core/mqtt/info", self._mqtt._core_info_payload(), retain=True, qos=1)
        if bootstrap_publish.get("ok") and info_publish.get("ok"):
            self._bootstrap_successes += 1
            self._bootstrap_last_success_at = _utcnow_iso()
            self._bootstrap_last_error = None
            return True
        self._bootstrap_last_error = str(
            bootstrap_publish.get("error")
            or info_publish.get("error")
            or "publish_failed"
        )
        return False

    def _record_reconcile_outcome(self, *, reason: str, result: StartupReconcileResult) -> None:
        self._last_reconcile_at = _utcnow_iso()
        self._last_reconcile_reason = str(reason)
        self._last_reconcile_status = result.status
        self._last_reconcile_error = result.error
        self._last_runtime_state = result.runtime_state

    async def _ensure_system_principals(self) -> None:
        from .integration_models import MqttPrincipal

        state = await self._state_store.get_state()
        existing = dict(state.principals or {})
        for principal_id in self._SYSTEM_PRINCIPAL_IDS:
            current = existing.get(principal_id)
            next_principal = current.model_copy(deep=True) if current is not None else MqttPrincipal(
                principal_id=principal_id,
                principal_type="system",
                status="active",
                logical_identity=principal_id,
            )
            next_principal.principal_type = "system"
            if next_principal.status in {"revoked", "expired"}:
                next_principal.status = "active"
            next_principal.managed_by = "core"
            next_principal.notes = "core_system_principal"
            await self._state_store.upsert_principal(next_principal)

    async def _activate_ready_addon_principals(self, *, reason: str) -> list[str]:
        from .integration_models import MqttPrincipal

        state = await self._state_store.get_state()
        activated: list[str] = []
        for addon_id in sorted(state.active_grants.keys()):
            grant = state.active_grants.get(addon_id)
            if grant is None:
                continue
            if grant.revocation_pending:
                continue
            if grant.status not in {"approved", "error", "provisioned"}:
                continue
            next_grant = grant.model_copy(deep=True)
            next_grant.status = "active"
            next_grant.last_error = None
            next_grant.last_provisioned_at = _utcnow_iso()
            next_grant.provision_contract = {
                "mode": "embedded_core_authority",
                "reason": f"runtime_apply:{reason}",
                "applied_at": _utcnow_iso(),
            }
            await self._state_store.upsert_grant(next_grant)
            principal_id = f"addon:{addon_id}"
            current_principal = state.principals.get(principal_id)
            next_principal = current_principal.model_copy(deep=True) if current_principal is not None else MqttPrincipal(
                principal_id=principal_id,
                principal_type="synthia_addon",
                status="active",
                logical_identity=addon_id,
                linked_addon_id=addon_id,
            )
            next_principal.principal_type = "synthia_addon"
            next_principal.logical_identity = addon_id
            next_principal.linked_addon_id = addon_id
            next_principal.status = "active"
            next_principal.publish_topics = sorted({str(topic).strip() for topic in next_grant.publish_topics if str(topic).strip()})
            next_principal.subscribe_topics = sorted({str(topic).strip() for topic in next_grant.subscribe_topics if str(topic).strip()})
            next_principal.managed_by = "authority"
            next_principal.last_activated_at = _utcnow_iso()
            next_principal.probation_reason = None
            await self._state_store.upsert_principal(next_principal)
            activated.append(addon_id)
        return activated
