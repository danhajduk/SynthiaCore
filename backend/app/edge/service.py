from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from fastapi import HTTPException

from app.system.audit import AuditLogStore
from app.system.onboarding import NodeRegistrationsStore
from app.system.platform_identity import (
    is_valid_core_id,
    load_platform_identity,
)
from app.supervisor.service import SupervisorDomainService

from .cloudflare_client import CloudflareApiClient, CloudflareApiError
from .cloudflare_renderer import CloudflareConfigRenderer
from .models import (
    CloudflareDnsResult,
    CloudflareProvisionResult,
    CloudflareSettings,
    CloudflareTunnelResult,
    CorePublicIdentity,
    EdgeDryRunResult,
    EdgePublication,
    EdgePublicationCreateRequest,
    EdgePublicationUpdateRequest,
    EdgeProvisioningState,
    EdgeStatus,
    EdgeTargetHealth,
    EdgeTunnelStatus,
    ProvisioningState,
    utcnow_iso,
)
from .store import EdgeGatewayStore

HOSTNAME_PATTERN = re.compile(r"^[a-z0-9.-]+$")
DEFAULT_CLOUDFLARE_API_TOKEN_REF = "env:CLOUDFLARE_API_TOKEN"
DEFAULT_CLOUDFLARE_ACCOUNT_ID_ENV = "CLOUDFLARE_ACCOUNT_ID"
DEFAULT_CLOUDFLARE_ZONE_ID_ENV = "CLOUDFLARE_ZONE_ID"


class EdgeGatewayService:
    def __init__(
        self,
        store: EdgeGatewayStore,
        *,
        settings_store=None,
        node_registrations_store: NodeRegistrationsStore | None = None,
        supervisor_service: SupervisorDomainService | None = None,
        renderer: CloudflareConfigRenderer | None = None,
        audit_store: AuditLogStore | None = None,
        cloudflare_client_factory=None,
    ) -> None:
        self._store = store
        self._settings_store = settings_store
        self._node_registrations_store = node_registrations_store
        self._supervisor_service = supervisor_service
        self._renderer = renderer or CloudflareConfigRenderer()
        self._audit_store = audit_store
        self._cloudflare_client_factory = cloudflare_client_factory or self._default_cloudflare_client

    async def public_identity(self) -> CorePublicIdentity:
        identity = await load_platform_identity(self._settings_store)
        return CorePublicIdentity(
            core_id=identity.core_id,
            core_name=identity.core_name,
            platform_domain=identity.platform_domain,
            public_ui_hostname=identity.public_ui_hostname,
            public_api_hostname=identity.public_api_hostname,
        )

    async def get_cloudflare_settings(self) -> CloudflareSettings:
        settings = await self._store.get_cloudflare_settings()
        return settings.model_copy(update={"api_token_configured": self._resolve_api_token(settings) is not None})

    async def update_cloudflare_settings(self, settings: CloudflareSettings) -> CloudflareSettings:
        current = await self._store.get_cloudflare_settings()
        normalized = settings.model_copy(
            update={
                "account_id": self._resolve_fixed_env(DEFAULT_CLOUDFLARE_ACCOUNT_ID_ENV) if settings.enabled else None,
                "zone_id": self._resolve_fixed_env(DEFAULT_CLOUDFLARE_ZONE_ID_ENV) if settings.enabled else None,
                "api_token_ref": DEFAULT_CLOUDFLARE_API_TOKEN_REF if settings.enabled else None,
                "managed_domain_base": str(settings.managed_domain_base or "").strip().lower() or "hexe-ai.com",
                "credentials_reference": str(settings.credentials_reference or "").strip() or None,
            }
        )
        self._validate_cloudflare_settings(normalized)
        reset_remote_state = self._cloudflare_context_changed(current, normalized)
        update_fields: dict[str, object] = {
            "api_token_configured": self._resolve_api_token(normalized) is not None,
            "updated_at": utcnow_iso(),
        }
        if reset_remote_state:
            update_fields.update(
                {
                    "tunnel_id": None,
                    "tunnel_name": None,
                    "tunnel_token_ref": None,
                    "ui_dns_record_id": None,
                    "api_dns_record_id": None,
                    "provisioning_state": ProvisioningState.not_configured,
                    "last_provisioned_at": None,
                    "last_provision_error": None,
                }
            )
        saved = await self._store.set_cloudflare_settings(
            normalized.model_copy(update=update_fields)
        )
        if reset_remote_state:
            await self._store.set_provisioning_state(EdgeProvisioningState())
            await self._store.set_reconcile_state({})
            await self._store.set_tunnel_status(EdgeTunnelStatus())
        await self._audit(
            "edge_cloudflare_settings_updated",
            {
                "enabled": saved.enabled,
                "zone_id": saved.zone_id,
                "tunnel_id": saved.tunnel_id,
                "api_token_ref": saved.api_token_ref,
                "reset_remote_state": reset_remote_state,
            },
        )
        return saved.model_copy(update={"api_token_configured": self._resolve_api_token(saved) is not None})

    async def list_publications(self) -> list[EdgePublication]:
        identity = await self.public_identity()
        publications = await self._store.list_publications()
        return self._inject_core_publications(publications, identity)

    async def create_publication(self, body: EdgePublicationCreateRequest) -> EdgePublication:
        publications = await self._store.list_publications()
        publication = EdgePublication(
            publication_id=f"edgepub-{len(publications)+1}",
            hostname=body.hostname.strip().lower(),
            path_prefix=body.path_prefix,
            enabled=body.enabled,
            source=body.source,
            target=body.target,
        )
        identity = await self.public_identity()
        self._validate_publication(publication, publications, identity)
        publications.append(publication)
        await self._store.set_publications(publications)
        await self._audit(
            "edge_publication_created",
            {"publication_id": publication.publication_id, "hostname": publication.hostname, "target_type": publication.target.target_type},
        )
        return publication

    async def update_publication(self, publication_id: str, body: EdgePublicationUpdateRequest) -> EdgePublication:
        publications = await self._store.list_publications()
        target_index = next((idx for idx, item in enumerate(publications) if item.publication_id == publication_id), None)
        if target_index is None:
            raise HTTPException(status_code=404, detail="edge_publication_not_found")
        current = publications[target_index]
        updated = current.model_copy(
            update={
                key: value
                for key, value in {
                    "hostname": body.hostname.strip().lower() if isinstance(body.hostname, str) else None,
                    "path_prefix": body.path_prefix,
                    "enabled": body.enabled,
                    "source": body.source,
                    "target": body.target,
                    "updated_at": utcnow_iso(),
                }.items()
                if value is not None
            }
        )
        remaining = [item for idx, item in enumerate(publications) if idx != target_index]
        identity = await self.public_identity()
        self._validate_publication(updated, remaining, identity)
        publications[target_index] = updated
        await self._store.set_publications(publications)
        await self._audit(
            "edge_publication_updated",
            {"publication_id": updated.publication_id, "hostname": updated.hostname, "enabled": updated.enabled},
        )
        return updated

    async def delete_publication(self, publication_id: str) -> None:
        publications = await self._store.list_publications()
        updated = [item for item in publications if item.publication_id != publication_id]
        await self._store.set_publications(updated)
        await self._audit("edge_publication_deleted", {"publication_id": publication_id})

    async def dry_run(self) -> EdgeDryRunResult:
        identity = await self.public_identity()
        settings = await self.get_cloudflare_settings()
        publications = await self._store.list_publications()
        validation_errors = self._collect_validation_errors(identity, settings, publications)
        rendered = self._renderer.render(identity=identity, settings=settings, publications=publications)
        result = EdgeDryRunResult(
            ok=not validation_errors,
            public_identity=identity,
            validation_errors=validation_errors,
            rendered_config=rendered,
            tunnel_name=self._tunnel_name(identity),
            dns_target=self._dns_target(settings),
        )
        await self._audit(
            "edge_cloudflare_dry_run_tested",
            {"ok": result.ok, "validation_errors": result.validation_errors, "tunnel_name": result.tunnel_name},
        )
        return result

    async def reconcile(self) -> dict[str, object]:
        result = await self._provision_and_reconcile(action="reconcile", live=True)
        reconcile_state: dict[str, object] = {
            "last_reconcile_at": utcnow_iso(),
            "last_status": "ok" if result.ok else "error",
            "last_error": None if result.ok else "; ".join(result.validation_errors or [str(result.provisioning.last_error or "reconcile_failed")]),
            "provisioning_state": result.provisioning.overall_state.value,
            "tunnel_id": result.provisioning.tunnel_id,
            "ui_dns_record_id": result.provisioning.ui_dns_record_id,
            "api_dns_record_id": result.provisioning.api_dns_record_id,
        }
        await self._store.set_reconcile_state(reconcile_state)
        await self._audit(
            "edge_reconcile_completed",
            {"status": reconcile_state.get("last_status"), "error": reconcile_state.get("last_error")},
        )
        return reconcile_state

    async def provision(self) -> CloudflareProvisionResult:
        return await self._provision_and_reconcile(action="provision", live=True)

    async def cloudflare_status(self) -> dict[str, object]:
        status = await self.status()
        return {
            "public_identity": status.public_identity.model_dump(mode="json"),
            "cloudflare": status.cloudflare.model_dump(mode="json"),
            "tunnel": status.tunnel.model_dump(mode="json"),
            "provisioning": status.provisioning.model_dump(mode="json"),
            "reconcile_state": status.reconcile_state,
            "validation_errors": status.validation_errors,
        }

    async def status(self) -> EdgeStatus:
        identity = await self.public_identity()
        settings = await self.get_cloudflare_settings()
        publications = await self.list_publications()
        tunnel = await self._store.get_tunnel_status()
        provisioning = await self._store.get_provisioning_state()
        reconcile_state = await self._store.get_reconcile_state()
        target_health = self._target_health(publications)
        validation_errors = self._collect_validation_errors(identity, settings, await self._store.list_publications())
        return EdgeStatus(
            public_identity=identity,
            cloudflare=settings,
            tunnel=tunnel,
            provisioning=provisioning,
            publications=publications,
            target_health=target_health,
            reconcile_state=reconcile_state,
            validation_errors=validation_errors,
        )

    def _target_health(self, publications: list[EdgePublication]) -> list[EdgeTargetHealth]:
        health: list[EdgeTargetHealth] = []
        for item in publications:
            detail = None
            state = "healthy"
            if item.target.target_type == "node":
                node = self._node_registrations_store.get(item.target.target_id) if self._node_registrations_store is not None else None
                if node is None or node.trust_status != "trusted":
                    state = "unavailable"
                    detail = "node_not_trusted"
            elif item.target.target_type == "supervisor_runtime" and self._supervisor_service is not None:
                runtime = self._supervisor_service.get_runtime_state(item.target.target_id)
                if not runtime.get("exists"):
                    state = "unavailable"
                    detail = "runtime_not_found"
            parsed = urlsplit(item.target.upstream_base_url)
            if parsed.hostname not in {"127.0.0.1", "localhost"}:
                state = "degraded"
                detail = "host_not_allowlisted"
            health.append(
                EdgeTargetHealth(
                    target_type=item.target.target_type,
                    target_id=item.target.target_id,
                    state=state,
                    detail=detail,
                )
            )
        return health

    def _inject_core_publications(
        self,
        publications: list[EdgePublication],
        identity: CorePublicIdentity,
    ) -> list[EdgePublication]:
        builtins = [
            EdgePublication(
                publication_id="core-ui",
                hostname=identity.public_ui_hostname,
                path_prefix="/",
                enabled=True,
                source="core_owned",
                target={
                    "target_type": "core_ui",
                    "target_id": "core-ui",
                    "upstream_base_url": "http://127.0.0.1:80",
                    "allowed_path_prefixes": ["/"],
                },
            ),
            EdgePublication(
                publication_id="core-api",
                hostname=identity.public_api_hostname,
                path_prefix="/",
                enabled=True,
                source="core_owned",
                target={
                    "target_type": "core_api",
                    "target_id": "core-api",
                    "upstream_base_url": "http://127.0.0.1:9001",
                    "allowed_path_prefixes": ["/"],
                },
            ),
        ]
        return builtins + sorted(publications, key=lambda item: (item.hostname, item.path_prefix, item.publication_id))

    def _collect_validation_errors(
        self,
        identity: CorePublicIdentity,
        settings: CloudflareSettings,
        publications: list[EdgePublication],
    ) -> list[str]:
        errors: list[str] = []
        if not is_valid_core_id(identity.core_id):
            errors.append("core_id_invalid")
        if settings.enabled:
            try:
                self._validate_cloudflare_settings(settings)
            except HTTPException as exc:
                errors.append(str(exc.detail))
        for publication in publications:
            try:
                self._validate_publication(publication, [item for item in publications if item.publication_id != publication.publication_id], identity)
            except HTTPException as exc:
                errors.append(f"{publication.publication_id}:{exc.detail}")
        return errors

    def _validate_cloudflare_settings(self, settings: CloudflareSettings) -> None:
        if settings.enabled and not all([settings.account_id, settings.zone_id, settings.api_token_ref]):
            raise HTTPException(status_code=400, detail="cloudflare_settings_incomplete")
        if str(settings.managed_domain_base or "").strip().lower() != "hexe-ai.com":
            raise HTTPException(status_code=400, detail="cloudflare_domain_base_invalid")
        if settings.enabled and settings.account_id != self._resolve_fixed_env(DEFAULT_CLOUDFLARE_ACCOUNT_ID_ENV):
            raise HTTPException(status_code=400, detail="cloudflare_account_id_unresolved")
        if settings.enabled and settings.zone_id != self._resolve_fixed_env(DEFAULT_CLOUDFLARE_ZONE_ID_ENV):
            raise HTTPException(status_code=400, detail="cloudflare_zone_id_unresolved")
        if settings.enabled and settings.api_token_ref != DEFAULT_CLOUDFLARE_API_TOKEN_REF:
            raise HTTPException(status_code=400, detail="cloudflare_api_token_ref_invalid")
        if settings.enabled and self._resolve_api_token(settings) is None:
            raise HTTPException(status_code=400, detail="cloudflare_api_token_unresolved")

    def _validate_publication(
        self,
        publication: EdgePublication,
        existing: list[EdgePublication],
        identity: CorePublicIdentity,
    ) -> None:
        hostname = str(publication.hostname or "").strip().lower()
        if not HOSTNAME_PATTERN.fullmatch(hostname):
            raise HTTPException(status_code=400, detail="edge_publication_hostname_invalid")
        if not hostname.endswith(f".{identity.platform_domain}"):
            raise HTTPException(status_code=400, detail="edge_publication_domain_invalid")
        if publication.source == "core_owned" and hostname not in {identity.public_ui_hostname, identity.public_api_hostname}:
            raise HTTPException(status_code=400, detail="edge_core_hostname_spoofed")
        if publication.target.target_type == "node":
            node = self._node_registrations_store.get(publication.target.target_id) if self._node_registrations_store is not None else None
            if node is None or node.trust_status != "trusted":
                raise HTTPException(status_code=400, detail="edge_target_node_not_trusted")
        if publication.target.target_type == "supervisor_runtime" and self._supervisor_service is not None:
            runtime = self._supervisor_service.get_runtime_state(publication.target.target_id)
            if not runtime.get("exists"):
                raise HTTPException(status_code=400, detail="edge_target_runtime_not_found")
        parsed = urlsplit(publication.target.upstream_base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise HTTPException(status_code=400, detail="edge_target_upstream_not_allowed")
        for item in existing:
            if item.hostname == hostname and item.path_prefix == publication.path_prefix:
                raise HTTPException(status_code=409, detail="edge_publication_conflict")

    async def _audit(self, event_type: str, details: dict[str, object]) -> None:
        if self._audit_store is None:
            return
        await self._audit_store.record(
            event_type=event_type,
            actor_role="admin",
            actor_id="edge_gateway",
            details=details,
        )

    async def _provision_and_reconcile(self, *, action: str, live: bool) -> CloudflareProvisionResult:
        identity = await self.public_identity()
        settings = await self.get_cloudflare_settings()
        publications = await self._store.list_publications()
        validation_errors = self._collect_validation_errors(identity, settings, publications)
        provisioning = await self._store.get_provisioning_state()
        await self._audit(
            f"edge_cloudflare_{action}_attempted",
            {"live": live, "enabled": settings.enabled, "validation_error_count": len(validation_errors)},
        )
        if validation_errors:
            provisioning = provisioning.model_copy(
                update={
                    "overall_state": ProvisioningState.error,
                    "last_action": action,
                    "last_error": "; ".join(validation_errors),
                }
            )
            await self._store.set_provisioning_state(provisioning)
            return CloudflareProvisionResult(
                ok=False,
                public_identity=identity,
                settings=settings,
                provisioning=provisioning,
                validation_errors=validation_errors,
                rendered_config=self._renderer.render(identity=identity, settings=settings, publications=publications),
            )

        tunnel_result: CloudflareTunnelResult | None = None
        dns_results: list[CloudflareDnsResult] = []
        settings_update: dict[str, object] = {
            "provisioning_state": ProvisioningState.pending,
            "last_provision_error": None,
        }
        await self._store.set_cloudflare_settings(settings.model_copy(update=settings_update))
        provisioning = provisioning.model_copy(
            update={
                "overall_state": ProvisioningState.pending if settings.enabled else ProvisioningState.not_configured,
                "tunnel_state": ProvisioningState.pending if settings.enabled else ProvisioningState.not_configured,
                "ui_hostname_state": ProvisioningState.pending if settings.enabled else ProvisioningState.not_configured,
                "api_hostname_state": ProvisioningState.pending if settings.enabled else ProvisioningState.not_configured,
                "dns_state": ProvisioningState.pending if settings.enabled else ProvisioningState.not_configured,
                "runtime_config_state": ProvisioningState.pending if settings.enabled else ProvisioningState.not_configured,
                "last_action": action,
                "last_error": None,
            }
        )
        await self._store.set_provisioning_state(provisioning)
        client = self._cloudflare_client_factory(settings)
        tunnel_token: str | None = None
        if live and settings.enabled and client is not None:
            try:
                tunnel_result = await self._ensure_tunnel(identity, settings, client)
                settings = settings.model_copy(
                    update={
                        "tunnel_id": tunnel_result.tunnel_id,
                        "tunnel_name": tunnel_result.tunnel_name,
                        "tunnel_token_ref": tunnel_result.tunnel_token_ref,
                    }
                )
                rendered_for_cloudflare = self._renderer.render(identity=identity, settings=settings, publications=publications)
                ingress_rules = rendered_for_cloudflare.get("ingress")
                if not isinstance(ingress_rules, list):
                    raise CloudflareApiError("update_tunnel_configuration", "cloudflare_ingress_invalid")
                await self._push_tunnel_configuration(tunnel_id=tunnel_result.tunnel_id, ingress=ingress_rules, client=client)
                tunnel_token = await client.get_tunnel_token(tunnel_result.tunnel_id)
                dns_results = await self._ensure_dns(identity, settings, client)
                settings = settings.model_copy(
                    update={
                        "ui_dns_record_id": dns_results[0].dns_record_id if len(dns_results) > 0 else settings.ui_dns_record_id,
                        "api_dns_record_id": dns_results[1].dns_record_id if len(dns_results) > 1 else settings.api_dns_record_id,
                        "last_provisioned_at": utcnow_iso(),
                        "last_provision_error": None,
                        "provisioning_state": ProvisioningState.provisioned,
                    }
                )
                provisioning = provisioning.model_copy(
                    update={
                        "overall_state": ProvisioningState.provisioned,
                        "tunnel_state": ProvisioningState.provisioned,
                        "ui_hostname_state": ProvisioningState.provisioned,
                        "api_hostname_state": ProvisioningState.provisioned,
                        "dns_state": ProvisioningState.provisioned,
                        "last_action": action,
                        "last_success_at": utcnow_iso(),
                        "last_error": None,
                        "tunnel_id": tunnel_result.tunnel_id,
                        "tunnel_name": tunnel_result.tunnel_name,
                        "ui_dns_record_id": dns_results[0].dns_record_id if len(dns_results) > 0 else None,
                        "api_dns_record_id": dns_results[1].dns_record_id if len(dns_results) > 1 else None,
                    }
                )
            except CloudflareApiError as exc:
                settings = settings.model_copy(update={"last_provision_error": str(exc), "provisioning_state": ProvisioningState.error})
                provisioning = provisioning.model_copy(
                    update={
                        "overall_state": ProvisioningState.error,
                        "last_action": action,
                        "last_error": str(exc),
                    }
                )
                await self._store.set_cloudflare_settings(settings)
                await self._store.set_provisioning_state(provisioning)
                await self._store.set_tunnel_status(
                    (await self._store.get_tunnel_status()).model_copy(
                        update={"last_error": str(exc), "updated_at": utcnow_iso(), "healthy": False}
                    )
                )
                await self._audit("edge_cloudflare_provision_failed", {"action": action, "error": str(exc)})
                return CloudflareProvisionResult(
                    ok=False,
                    public_identity=identity,
                    settings=settings,
                    provisioning=provisioning,
                    tunnel=tunnel_result,
                    dns_records=dns_results,
                    validation_errors=[],
                    rendered_config=self._renderer.render(identity=identity, settings=settings, publications=publications),
                )

        rendered = self._renderer.render(identity=identity, settings=settings, publications=publications)
        apply_result = None
        if self._supervisor_service is not None:
            apply_result = self._supervisor_service.apply_cloudflared_config(
                {
                    **rendered,
                    "desired_enabled": bool(settings.enabled),
                    "provisioning_state": provisioning.overall_state.value,
                    "tunnel-token": tunnel_token,
                }
            )
            tunnel_status = (await self._store.get_tunnel_status()).model_copy(
                update={
                    "configured": True,
                    "runtime_state": str(apply_result.get("runtime_state") or "configured"),
                    "healthy": bool(apply_result.get("ok")),
                    "config_path": str(apply_result.get("config_path") or ""),
                    "last_error": None if bool(apply_result.get("ok")) else str(apply_result.get("error") or "unknown"),
                    "tunnel_id": settings.tunnel_id,
                    "tunnel_name": settings.tunnel_name,
                    "updated_at": utcnow_iso(),
                }
            )
            await self._store.set_tunnel_status(tunnel_status)
            await self._audit(
                "edge_cloudflare_runtime_applied",
                {"ok": bool(apply_result.get("ok")), "runtime_state": apply_result.get("runtime_state")},
            )
            provisioning = provisioning.model_copy(
                update={
                    "runtime_config_state": ProvisioningState.provisioned if bool(apply_result.get("ok")) else ProvisioningState.degraded,
                    "overall_state": provisioning.overall_state if bool(apply_result.get("ok")) else ProvisioningState.degraded,
                    "last_error": None if bool(apply_result.get("ok")) else str(apply_result.get("error") or "runtime_apply_failed"),
                }
            )
        await self._store.set_cloudflare_settings(settings.model_copy(update={"api_token_configured": self._resolve_api_token(settings) is not None}))
        await self._store.set_provisioning_state(provisioning)
        if action == "provision":
            await self._audit(
                "edge_cloudflare_provision_completed",
                {"ok": True, "tunnel_id": settings.tunnel_id, "ui_dns_record_id": settings.ui_dns_record_id, "api_dns_record_id": settings.api_dns_record_id},
            )
        return CloudflareProvisionResult(
            ok=not validation_errors and provisioning.overall_state != ProvisioningState.error,
            public_identity=identity,
            settings=settings,
            provisioning=provisioning,
            tunnel=tunnel_result,
            dns_records=dns_results,
            validation_errors=validation_errors,
            rendered_config=rendered,
        )

    def _tunnel_name(self, identity: CorePublicIdentity) -> str:
        return f"hexe-core-{identity.core_id}"

    def _dns_target(self, settings: CloudflareSettings) -> str | None:
        tunnel_id = str(settings.tunnel_id or "").strip()
        if not tunnel_id:
            return None
        return f"{tunnel_id}.cfargotunnel.com"

    def _resolve_api_token(self, settings: CloudflareSettings) -> str | None:
        ref = str(settings.api_token_ref or "").strip()
        if not ref:
            return None
        env_name = ref[4:] if ref.startswith("env:") else ref
        token = str(os.getenv(env_name, "")).strip()
        return token or None

    def _resolve_fixed_env(self, env_name: str) -> str | None:
        value = str(os.getenv(env_name, "")).strip()
        return value or None

    def _cloudflare_context_changed(self, current: CloudflareSettings, updated: CloudflareSettings) -> bool:
        tracked_fields = (
            "enabled",
            "account_id",
            "zone_id",
            "managed_domain_base",
        )
        return any(getattr(current, field) != getattr(updated, field) for field in tracked_fields)

    def _default_cloudflare_client(self, settings: CloudflareSettings) -> CloudflareApiClient | None:
        token = self._resolve_api_token(settings)
        if token is None or not settings.account_id or not settings.zone_id:
            return None
        return CloudflareApiClient(api_token=token, account_id=settings.account_id, zone_id=settings.zone_id)

    async def _ensure_tunnel(
        self,
        identity: CorePublicIdentity,
        settings: CloudflareSettings,
        client: CloudflareApiClient,
    ) -> CloudflareTunnelResult:
        desired_name = self._tunnel_name(identity)
        tunnel = None
        if settings.tunnel_id:
            tunnel = await client.get_tunnel(settings.tunnel_id)
        if tunnel is None:
            tunnel = await client.find_tunnel_by_name(settings.tunnel_name or desired_name)
        if tunnel is None:
            tunnel = await client.create_tunnel(desired_name)
            await self._audit("edge_cloudflare_tunnel_created", {"tunnel_id": tunnel.tunnel_id, "tunnel_name": tunnel.tunnel_name})
        tunnel_token = await client.get_tunnel_token(tunnel.tunnel_id)
        tunnel_token_ref = settings.tunnel_token_ref or (f"cloudflare-tunnel:{tunnel.tunnel_id}" if tunnel_token else None)
        return CloudflareTunnelResult(
            tunnel_id=tunnel.tunnel_id,
            tunnel_name=tunnel.tunnel_name or desired_name,
            tunnel_token_ref=tunnel_token_ref,
        )

    async def _push_tunnel_configuration(
        self,
        *,
        tunnel_id: str,
        ingress: list[dict[str, object]],
        client: CloudflareApiClient,
    ) -> dict[str, object]:
        result = await client.update_tunnel_configuration(tunnel_id=tunnel_id, ingress=ingress)
        await self._audit("edge_cloudflare_tunnel_config_updated", {"tunnel_id": tunnel_id, "ingress_rule_count": len(ingress)})
        return result if isinstance(result, dict) else {}

    async def _ensure_dns(
        self,
        identity: CorePublicIdentity,
        settings: CloudflareSettings,
        client: CloudflareApiClient,
    ) -> list[CloudflareDnsResult]:
        dns_target = self._dns_target(settings.model_copy(update={"tunnel_id": settings.tunnel_id}))
        if not dns_target:
            raise CloudflareApiError("dns_target", "cloudflare_tunnel_missing")
        ui = await client.upsert_dns_record(hostname=identity.public_ui_hostname, content=dns_target, proxied=True)
        api = await client.upsert_dns_record(hostname=identity.public_api_hostname, content=dns_target, proxied=True)
        await self._audit("edge_cloudflare_dns_reconciled", {"hostnames": [identity.public_ui_hostname, identity.public_api_hostname]})
        return [
            CloudflareDnsResult(hostname=ui.name, dns_record_id=ui.record_id, content=ui.content, proxied=ui.proxied),
            CloudflareDnsResult(hostname=api.name, dns_record_id=api.record_id, content=api.content, proxied=api.proxied),
        ]
