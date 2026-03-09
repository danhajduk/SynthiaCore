from __future__ import annotations

import os
from dataclasses import dataclass

from .acl_compiler import MqttAclCompiler
from .apply_pipeline import MqttApplyPipeline
from .authority_audit import MqttAuthorityAuditStore
from .config_renderer import MqttBrokerConfigRenderer, MqttBrokerRenderInput, MqttListenerSpec
from .integration_models import MqttBootstrapAnnouncement, MqttSetupStateUpdate
from .integration_state import MqttIntegrationStateStore


@dataclass(frozen=True)
class StartupReconcileResult:
    ok: bool
    status: str
    setup_status: str
    runtime_state: str
    error: str | None = None


class EmbeddedMqttStartupReconciler:
    def __init__(
        self,
        *,
        state_store: MqttIntegrationStateStore,
        acl_compiler: MqttAclCompiler,
        config_renderer: MqttBrokerConfigRenderer,
        apply_pipeline: MqttApplyPipeline,
        audit_store: MqttAuthorityAuditStore,
        mqtt_manager,
    ) -> None:
        self._state_store = state_store
        self._acl_compiler = acl_compiler
        self._renderer = config_renderer
        self._pipeline = apply_pipeline
        self._audit = audit_store
        self._mqtt = mqtt_manager

    async def reconcile_startup(self) -> StartupReconcileResult:
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
                        MqttListenerSpec(name="bootstrap", enabled=True, port=1884),
                    ],
                )
            )
            artifacts = dict(rendered.files)
            artifacts["acl_compiled.conf"] = acl.acl_text
            artifacts["passwords.conf"] = "# managed by synthia core\n"
            apply_result = await self._pipeline.apply(artifacts)
            authority_ready = bool(apply_result.ok and apply_result.runtime.healthy)
            next_setup = MqttSetupStateUpdate(
                requires_setup=state.requires_setup,
                setup_complete=authority_ready,
                setup_status=("ready" if authority_ready else "degraded"),
                broker_mode=state.broker_mode,
                direct_mqtt_supported=state.direct_mqtt_supported,
                setup_error=(None if authority_ready else (apply_result.error or "reconcile_failed")),
                authority_mode="embedded_platform",
                authority_ready=authority_ready,
            )
            await self._state_store.update_setup_state(next_setup)
            if authority_ready:
                await self._publish_bootstrap()
            await self._audit.append_event(
                event_type="mqtt_startup_reconcile",
                status=("ok" if authority_ready else "degraded"),
                message=None if authority_ready else (apply_result.error or "reconcile_failed"),
                payload={
                    "runtime_state": apply_result.runtime.state,
                    "runtime_healthy": apply_result.runtime.healthy,
                },
            )
            return StartupReconcileResult(
                ok=authority_ready,
                status=("ok" if authority_ready else "degraded"),
                setup_status=next_setup.setup_status,
                runtime_state=apply_result.runtime.state,
                error=(None if authority_ready else apply_result.error),
            )
        except Exception as exc:
            await self._audit.append_event(
                event_type="mqtt_startup_reconcile",
                status="error",
                message=type(exc).__name__,
                payload={"detail": str(exc)},
            )
            return StartupReconcileResult(False, "error", "degraded", "unknown", error=type(exc).__name__)

    async def _publish_bootstrap(self) -> None:
        core_id = "synthia-core"
        core_name = "Synthia Core"
        api_base = "http://127.0.0.1:9001/api"
        payload = MqttBootstrapAnnouncement(
            core_id=core_id,
            core_name=core_name,
            api_base=api_base,
            onboarding_endpoints={
                "register": "/api/system/mqtt/registrations/approve",
                "setup_state": "/api/system/mqtt/setup-state",
            },
            onboarding_mode="api",
        ).model_dump(mode="json")
        await self._mqtt.publish("synthia/bootstrap/core", payload, retain=True, qos=1)
        await self._mqtt.publish("synthia/core/mqtt/info", self._mqtt._core_info_payload(), retain=True, qos=1)
