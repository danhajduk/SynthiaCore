from __future__ import annotations

from typing import Any
from pathlib import Path
import socket

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.admin import require_admin_token
from app.system.auth import ServiceTokenError, ServiceTokenKeyStore, validate_claims, verify_hs256

from .acl_compiler import MqttAclCompiler
from .approval import MqttRegistrationApprovalService
from .integration_models import MqttRegistrationRequest, MqttSetupStateUpdate
from .integration_state import MqttIntegrationStateStore
from .manager import MqttManager
from .topic_policy import validate_topic_scopes


class MqttTestRequest(BaseModel):
    topic: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class MqttTopicValidationRequest(BaseModel):
    addon_id: str = Field(..., min_length=1)
    publish_topics: list[str] = Field(default_factory=list)
    subscribe_topics: list[str] = Field(default_factory=list)
    approved_reserved_topics: list[str] = Field(default_factory=list)


class MqttPrincipalActionRequest(BaseModel):
    reason: str | None = None


class MqttGenericUserUpsertRequest(BaseModel):
    principal_id: str = Field(..., min_length=1)
    logical_identity: str = Field(..., min_length=1)
    username: str | None = None
    publish_topics: list[str] = Field(default_factory=list)
    subscribe_topics: list[str] = Field(default_factory=list)
    notes: str | None = None


class MqttGenericUserGrantUpdateRequest(BaseModel):
    publish_topics: list[str] = Field(default_factory=list)
    subscribe_topics: list[str] = Field(default_factory=list)
    notes: str | None = None


class MqttNoisyActionRequest(BaseModel):
    reason: str | None = None


class MqttSetupApplyRequest(BaseModel):
    mode: str = "local"
    host: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    tls_enabled: bool = False
    keepalive_s: int = Field(default=30, ge=1)
    client_id: str = "synthia-core"
    initialize: bool = True


class MqttSetupConnectionTestRequest(BaseModel):
    host: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)
    timeout_s: float = Field(default=2.0, gt=0.0, le=10.0)


async def _authorize_mqtt_request(
    *,
    request: Request,
    x_admin_token: str | None,
    authorization: str | None,
    key_store: ServiceTokenKeyStore,
    required_scope: str | None = None,
) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            _, payload = verify_hs256(token, await key_store.all_keys())
            claims = validate_claims(
                payload,
                audience="synthia-core",
                required_scopes=[required_scope] if required_scope else None,
            )
            return claims.sub
        except ServiceTokenError as exc:
            raise HTTPException(status_code=401, detail=str(exc))
    require_admin_token(x_admin_token, request)
    return None


def build_mqtt_router(
    manager: MqttManager,
    registry,
    state_store: MqttIntegrationStateStore,
    key_store: ServiceTokenKeyStore,
    settings_store=None,
    approval_service: MqttRegistrationApprovalService | None = None,
    acl_compiler: MqttAclCompiler | None = None,
    credential_store=None,
    runtime_reconciler=None,
    runtime_boundary=None,
    observability_store=None,
    audit_store=None,
) -> APIRouter:
    router = APIRouter()
    approval = approval_service or MqttRegistrationApprovalService(registry=registry, state_store=state_store)

    def _runtime_status_payload(status: Any) -> dict[str, Any]:
        if isinstance(status, dict):
            return dict(status)
        return {
            "provider": getattr(status, "provider", "unknown"),
            "state": getattr(status, "state", "unknown"),
            "healthy": bool(getattr(status, "healthy", False)),
            "degraded_reason": getattr(status, "degraded_reason", None),
            "checked_at": getattr(status, "checked_at", None),
        }

    def _reconcile_payload(result: Any) -> dict[str, Any]:
        if result is None:
            return {}
        if isinstance(result, dict):
            return dict(result)
        dump = getattr(result, "model_dump", None)
        if callable(dump):
            try:
                return dict(dump(mode="json"))
            except Exception:
                pass
        return {
            "ok": bool(getattr(result, "ok", False)),
            "status": getattr(result, "status", "unknown"),
            "setup_status": getattr(result, "setup_status", "unknown"),
            "runtime_state": getattr(result, "runtime_state", "unknown"),
            "error": getattr(result, "error", None),
        }

    async def _audit_runtime_action(
        *,
        action: str,
        status: str,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if audit_store is None:
            return
        append_event = getattr(audit_store, "append_event", None)
        if not callable(append_event):
            return
        await append_event(
            event_type="mqtt_runtime_control",
            status=status,
            message=message,
            payload={"action": action, **(payload or {})},
        )

    async def _manager_status_safe() -> dict[str, Any]:
        try:
            return await manager.status()
        except Exception as exc:
            return {"ok": False, "error": f"status_failed:{type(exc).__name__}"}

    def _runtime_required() -> Any:
        if runtime_boundary is None:
            raise HTTPException(status_code=503, detail="runtime_boundary_unavailable")
        return runtime_boundary

    def _runtime_reconciler_callable():
        if runtime_reconciler is None:
            return None
        fn = getattr(runtime_reconciler, "reconcile_authority", None)
        if callable(fn):
            return fn
        return None

    def _settings_required() -> Any:
        if settings_store is None:
            raise HTTPException(status_code=503, detail="settings_store_unavailable")
        return settings_store

    def _normalized_mode(mode: str) -> str:
        return "external" if str(mode or "").strip().lower() == "external" else "local"

    def _test_tcp_connection(host: str, port: int, timeout_s: float = 2.0) -> dict[str, Any]:
        trimmed_host = str(host or "").strip()
        if not trimmed_host:
            return {"ok": False, "result": "invalid_input", "detail": "host_required"}
        try:
            with socket.create_connection((trimmed_host, int(port)), timeout=float(timeout_s)):
                return {"ok": True, "result": "reachable", "detail": "tcp_connect_ok"}
        except TimeoutError:
            return {"ok": False, "result": "timeout", "detail": "connect_timeout"}
        except ValueError:
            return {"ok": False, "result": "invalid_input", "detail": "invalid_port"}
        except OSError:
            return {"ok": False, "result": "unreachable", "detail": "connect_failed"}
        except Exception:
            return {"ok": False, "result": "unreachable", "detail": "connect_failed"}

    async def _ensure_runtime_with_config_retry(
        runtime,
        *,
        retry_reason: str,
        reconcile_payload: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        existing = dict(reconcile_payload or {})
        status = await runtime.ensure_running()
        payload = _runtime_status_payload(status)
        if payload.get("healthy"):
            return payload, existing
        reason = str(payload.get("degraded_reason") or "").strip().lower()
        reconcile_fn = _runtime_reconciler_callable()
        if reason == "config_missing" and reconcile_fn is not None:
            retried = await reconcile_fn(reason=retry_reason)
            existing = _reconcile_payload(retried)
            status = await runtime.ensure_running()
            payload = _runtime_status_payload(status)
        return payload, existing

    @router.get("/mqtt/status")
    async def mqtt_status():
        return await manager.status()

    @router.post("/mqtt/test")
    async def mqtt_test(body: MqttTestRequest):
        payload = body.payload if body.payload else None
        return await manager.publish_test(topic=body.topic, payload=payload)

    @router.post("/mqtt/restart")
    async def mqtt_restart():
        await manager.restart()
        return await manager.status()

    @router.post("/mqtt/reload")
    async def mqtt_reload():
        if runtime_reconciler is not None:
            await runtime_reconciler.reconcile_authority(reason="api_reload")
        else:
            await manager.restart()
        return await manager.status()

    @router.post("/mqtt/setup/test-connection")
    async def mqtt_setup_test_connection(
        body: MqttSetupConnectionTestRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        tested = _test_tcp_connection(body.host, body.port, body.timeout_s)
        return {
            "ok": bool(tested.get("ok")),
            "result": tested.get("result", "unreachable"),
            "detail": tested.get("detail"),
            "host": body.host,
            "port": body.port,
        }

    @router.post("/mqtt/setup/apply")
    async def mqtt_setup_apply(
        body: MqttSetupApplyRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        settings = _settings_required()
        mode = _normalized_mode(body.mode)
        host = str(body.host or "").strip()
        port = int(body.port)
        if not host:
            raise HTTPException(status_code=400, detail="setup_host_required")
        if port <= 0 or port > 65535:
            raise HTTPException(status_code=400, detail="setup_port_invalid")
        if body.keepalive_s <= 0:
            raise HTTPException(status_code=400, detail="setup_keepalive_invalid")

        await settings.set("mqtt.mode", mode)
        await settings.set(f"mqtt.{mode}.host", host)
        await settings.set(f"mqtt.{mode}.port", port)
        await settings.set(f"mqtt.{mode}.username", str(body.username or "").strip())
        await settings.set(f"mqtt.{mode}.password", str(body.password or ""))
        await settings.set(f"mqtt.{mode}.tls_enabled", bool(body.tls_enabled))
        await settings.set("mqtt.keepalive_s", int(body.keepalive_s))
        await settings.set("mqtt.client_id", str(body.client_id or "").strip() or "synthia-core")

        external_probe = None
        reconcile_payload: dict[str, Any] = {}
        runtime_payload: dict[str, Any] = {}
        status_payload: dict[str, Any] = {}
        setup_update: MqttSetupStateUpdate | None = None

        if mode == "external":
            external_probe = _test_tcp_connection(host, port, 2.0)
            ready = bool(external_probe.get("ok"))
            setup_update = MqttSetupStateUpdate(
                requires_setup=True,
                setup_complete=ready,
                setup_status=("ready" if ready else "degraded"),
                broker_mode="external",
                direct_mqtt_supported=True,
                setup_error=(None if ready else f"external_broker_{external_probe.get('result', 'unreachable')}"),
                authority_mode="embedded_platform",
                authority_ready=ready,
            )
            await approval.update_setup_state(setup_update)
            if body.initialize and ready:
                await manager.restart()
                status_payload = await _manager_status_safe()
        else:
            runtime = _runtime_required()
            reconcile_fn = _runtime_reconciler_callable()
            if reconcile_fn is not None:
                reconcile_result = await reconcile_fn(reason="api_setup_apply_local")
                reconcile_payload = _reconcile_payload(reconcile_result)
            runtime_payload, reconcile_payload = await _ensure_runtime_with_config_retry(
                runtime,
                retry_reason="api_setup_apply_local_config_missing",
                reconcile_payload=reconcile_payload,
            )
            if body.initialize and bool(runtime_payload.get("healthy")):
                await manager.restart()
            status_payload = await _manager_status_safe()
            ready = bool(runtime_payload.get("healthy"))
            setup_update = MqttSetupStateUpdate(
                requires_setup=True,
                setup_complete=ready,
                setup_status=("ready" if ready else "degraded"),
                broker_mode="local",
                direct_mqtt_supported=False,
                setup_error=(None if ready else str(runtime_payload.get("degraded_reason") or "runtime_unhealthy")),
                authority_mode="embedded_platform",
                authority_ready=ready,
            )
            await approval.update_setup_state(setup_update)

        setup_summary = await approval.setup_summary()
        broker_summary = await approval.broker_summary()
        await _audit_runtime_action(
            action="setup_apply",
            status=("ok" if setup_summary.setup_ready else "degraded"),
            message=(None if setup_summary.setup_ready else setup_summary.setup_error),
            payload={
                "mode": mode,
                "host": host,
                "port": port,
                "initialize": bool(body.initialize),
                "setup_status": setup_summary.setup_status,
                "external_probe": external_probe,
                "runtime": runtime_payload,
                "reconciliation": reconcile_payload,
            },
        )
        return {
            "ok": bool(setup_summary.setup_ready),
            "mode": mode,
            "setup": setup_summary.model_dump(mode="json"),
            "broker": broker_summary.model_dump(mode="json"),
            "health": status_payload,
            "runtime": runtime_payload,
            "reconciliation": reconcile_payload,
            "external_probe": external_probe,
        }

    @router.get("/mqtt/runtime/health")
    async def mqtt_runtime_health(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        runtime = _runtime_required()
        runtime_status = await runtime.health_check()
        health = await _manager_status_safe()
        return {
            "ok": True,
            "action": "health",
            "runtime": _runtime_status_payload(runtime_status),
            "health": health,
        }

    @router.post("/mqtt/runtime/start")
    async def mqtt_runtime_start(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        runtime = _runtime_required()
        runtime_payload, reconcile_payload = await _ensure_runtime_with_config_retry(
            runtime,
            retry_reason="api_runtime_start_config_missing",
        )
        if bool(runtime_payload.get("healthy")):
            await manager.restart()
        health = await _manager_status_safe()
        result = {
            "ok": bool(runtime_payload.get("healthy", False)),
            "action": "start",
            "runtime": runtime_payload,
            "health": health,
            "reconciliation": reconcile_payload,
        }
        await _audit_runtime_action(
            action="start",
            status=("ok" if result["ok"] else "degraded"),
            message=result["runtime"].get("degraded_reason"),
            payload={
                "runtime": result["runtime"],
                "reconciliation": reconcile_payload,
                "health_connected": bool(health.get("connected")),
            },
        )
        return result

    @router.post("/mqtt/runtime/stop")
    async def mqtt_runtime_stop(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        runtime = _runtime_required()
        runtime_status = await runtime.stop()
        stop = getattr(manager, "stop", None)
        if callable(stop):
            await stop()
        health = await _manager_status_safe()
        runtime_payload = _runtime_status_payload(runtime_status)
        stopped = str(runtime_payload.get("state") or "").lower() == "stopped"
        result = {
            "ok": stopped,
            "action": "stop",
            "runtime": runtime_payload,
            "health": health,
        }
        await _audit_runtime_action(
            action="stop",
            status=("ok" if result["ok"] else "degraded"),
            message=runtime_payload.get("degraded_reason"),
            payload={"runtime": runtime_payload, "health_connected": bool(health.get("connected"))},
        )
        return result

    @router.post("/mqtt/runtime/init")
    async def mqtt_runtime_init(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        runtime = _runtime_required()
        reconcile_result = None
        reconcile_fn = _runtime_reconciler_callable()
        if reconcile_fn is not None:
            reconcile_result = await reconcile_fn(reason="api_runtime_init")
        reconcile_payload = _reconcile_payload(reconcile_result)
        runtime_payload, reconcile_payload = await _ensure_runtime_with_config_retry(
            runtime,
            retry_reason="api_runtime_init_config_missing",
            reconcile_payload=reconcile_payload,
        )
        if bool(runtime_payload.get("healthy")):
            await manager.restart()
        health = await _manager_status_safe()
        result = {
            "ok": bool(runtime_payload.get("healthy", False)),
            "action": "init",
            "runtime": runtime_payload,
            "health": health,
            "reconciliation": reconcile_payload,
        }
        await _audit_runtime_action(
            action="init",
            status=("ok" if result["ok"] else "degraded"),
            message=result["runtime"].get("degraded_reason"),
            payload={
                "runtime": result["runtime"],
                "reconciliation": result["reconciliation"],
                "health_connected": bool(health.get("connected")),
            },
        )
        return result

    @router.post("/mqtt/runtime/rebuild")
    async def mqtt_runtime_rebuild(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        runtime = _runtime_required()
        reconcile_result = None
        if runtime_reconciler is not None and hasattr(runtime_reconciler, "reconcile_authority"):
            reconcile_result = await runtime_reconciler.reconcile_authority(reason="api_runtime_rebuild")
            runtime_status = await runtime.health_check()
        else:
            runtime_status = await runtime.controlled_restart()
        if getattr(runtime_status, "healthy", False):
            await manager.restart()
        health = await _manager_status_safe()
        result = {
            "ok": bool(getattr(runtime_status, "healthy", False)),
            "action": "rebuild",
            "runtime": _runtime_status_payload(runtime_status),
            "health": health,
            "reconciliation": _reconcile_payload(reconcile_result),
        }
        await _audit_runtime_action(
            action="rebuild",
            status=("ok" if result["ok"] else "degraded"),
            message=result["runtime"].get("degraded_reason"),
            payload={
                "runtime": result["runtime"],
                "reconciliation": result["reconciliation"],
                "health_connected": bool(health.get("connected")),
            },
        )
        return result

    @router.post("/mqtt/registrations/approve")
    async def mqtt_registration_approve(
        body: MqttRegistrationRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        subject = await _authorize_mqtt_request(
            request=request,
            x_admin_token=x_admin_token,
            authorization=authorization,
            key_store=key_store,
            required_scope="mqtt.register",
        )
        result = await approval.approve(body, requested_by_subject=subject)
        return {"ok": result.status == "approved", "result": result.model_dump(mode="json")}

    @router.post("/mqtt/registrations/{addon_id}/provision")
    async def mqtt_registration_provision(
        addon_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        subject = await _authorize_mqtt_request(
            request=request,
            x_admin_token=x_admin_token,
            authorization=authorization,
            key_store=key_store,
            required_scope="mqtt.provision",
        )
        if subject and subject != addon_id:
            return {"ok": False, "addon_id": addon_id, "status": "rejected", "error": "request_subject_mismatch"}
        return await approval.provision_grant(addon_id, reason="api_request")

    @router.post("/mqtt/registrations/{addon_id}/revoke")
    async def mqtt_registration_revoke(
        addon_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        subject = await _authorize_mqtt_request(
            request=request,
            x_admin_token=x_admin_token,
            authorization=authorization,
            key_store=key_store,
            required_scope="mqtt.revoke",
        )
        if subject and subject != addon_id:
            return {"ok": False, "addon_id": addon_id, "status": "rejected", "error": "request_subject_mismatch"}
        return await approval.revoke_or_mark(addon_id, reason="api_request")

    @router.get("/mqtt/grants")
    async def mqtt_grants(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        items = await approval.list_grants()
        return {"ok": True, "items": items}

    @router.get("/mqtt/grants/{addon_id}")
    async def mqtt_grant(addon_id: str, request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        item = await approval.get_grant(addon_id)
        if item is None:
            raise HTTPException(status_code=404, detail="mqtt_grant_not_found")
        return {"ok": True, "grant": item}

    @router.get("/mqtt/principals")
    async def mqtt_principals(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        return {"ok": True, "items": await approval.list_principals()}

    @router.post("/mqtt/principals/{principal_id}/actions/{action}")
    async def mqtt_principal_action(
        principal_id: str,
        action: str,
        body: MqttPrincipalActionRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        result = await approval.apply_principal_action(principal_id, action, reason=body.reason)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=str(result.get("error") or "principal_action_failed"))
        return result

    @router.post("/mqtt/generic-users")
    async def mqtt_generic_user_upsert(
        body: MqttGenericUserUpsertRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        result = await approval.create_or_update_generic_user(
            principal_id=body.principal_id,
            logical_identity=body.logical_identity,
            username=body.username,
            publish_topics=body.publish_topics,
            subscribe_topics=body.subscribe_topics,
            notes=body.notes,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=str(result.get("error") or "generic_user_upsert_failed"))
        return result

    @router.patch("/mqtt/generic-users/{principal_id}/grants")
    async def mqtt_generic_user_update_grants(
        principal_id: str,
        body: MqttGenericUserGrantUpdateRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        existing = await approval.get_principal(principal_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="principal_not_found")
        result = await approval.create_or_update_generic_user(
            principal_id=principal_id,
            logical_identity=str(existing.get("logical_identity") or principal_id),
            username=(str(existing.get("username")) if existing.get("username") else None),
            publish_topics=body.publish_topics,
            subscribe_topics=body.subscribe_topics,
            notes=body.notes if body.notes is not None else existing.get("notes"),
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=str(result.get("error") or "generic_user_update_failed"))
        return result

    @router.post("/mqtt/generic-users/{principal_id}/revoke")
    async def mqtt_generic_user_revoke(
        principal_id: str,
        body: MqttPrincipalActionRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        result = await approval.apply_principal_action(principal_id, "revoke", reason=body.reason or "generic_user_revoke")
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=str(result.get("error") or "generic_user_revoke_failed"))
        return result

    @router.post("/mqtt/generic-users/{principal_id}/rotate-credentials")
    async def mqtt_generic_user_rotate_credentials(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        result = await approval.apply_noisy_client_action(principal_id, "revoke_credentials", reason="rotate_credentials")
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=str(result.get("error") or "rotate_credentials_failed"))
        return {"ok": True, "principal_id": principal_id, "rotated": bool(result.get("rotated"))}

    @router.get("/mqtt/generic-users/{principal_id}/effective-access")
    async def mqtt_generic_user_effective_access(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        compiler = acl_compiler or getattr(runtime_reconciler, "_acl_compiler", None)
        if compiler is None:
            raise HTTPException(status_code=503, detail="acl_compiler_unavailable")
        state = await state_store.get_state()
        access = compiler.inspect_effective_access(state, principal_id)
        if access is None:
            raise HTTPException(status_code=404, detail="principal_not_found")
        return {"ok": True, "principal_id": principal_id, "effective_access": access.__dict__}

    @router.get("/mqtt/debug/effective-access/{principal_id}")
    async def mqtt_debug_effective_access(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        compiler = acl_compiler or getattr(runtime_reconciler, "_acl_compiler", None)
        if compiler is None:
            raise HTTPException(status_code=503, detail="acl_compiler_unavailable")
        state = await state_store.get_state()
        access = compiler.inspect_effective_access(state, principal_id)
        if access is None:
            raise HTTPException(status_code=404, detail="principal_not_found")
        return {"ok": True, "principal_id": principal_id, "effective_access": access.__dict__}

    @router.get("/mqtt/noisy-clients")
    async def mqtt_noisy_clients(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        items = await approval.list_noisy_clients()
        return {"ok": True, "items": items}

    @router.post("/mqtt/noisy-clients/{principal_id}/actions/{action}")
    async def mqtt_noisy_client_action(
        principal_id: str,
        action: str,
        body: MqttNoisyActionRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        result = await approval.apply_noisy_client_action(principal_id, action, reason=body.reason)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=str(result.get("error") or "noisy_action_failed"))
        return result

    @router.get("/mqtt/observability")
    async def mqtt_observability_events(
        request: Request,
        x_admin_token: str | None = Header(default=None),
        limit: int = 100,
    ):
        require_admin_token(x_admin_token, request)
        if observability_store is None:
            return {"ok": True, "items": []}
        return {"ok": True, "items": await observability_store.list_events(limit=limit)}

    @router.get("/mqtt/audit")
    async def mqtt_authority_audit_events(
        request: Request,
        x_admin_token: str | None = Header(default=None),
        limit: int = 100,
    ):
        require_admin_token(x_admin_token, request)
        if audit_store is None:
            return {"ok": True, "items": []}
        return {"ok": True, "items": await audit_store.list_events(limit=limit)}

    @router.get("/mqtt/setup-summary")
    async def mqtt_setup_summary(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        setup = await approval.setup_summary()
        broker = await approval.broker_summary()
        health = await manager.status()
        grants = await approval.list_grants()
        last_authority_errors = [
            {
                "addon_id": item.get("addon_id"),
                "status": item.get("status"),
                "last_error": item.get("last_error"),
                "updated_at": item.get("updated_at"),
            }
            for item in grants
            if item.get("last_error")
        ]
        reasons: list[str] = []
        runtime_connected = bool(health.get("connected"))
        if not setup.authority_ready:
            reasons.append("authority_not_ready")
        if not setup.setup_ready:
            reasons.append("setup_not_ready")
        if not runtime_connected:
            reasons.append("mqtt_runtime_not_connected")
        effective = {
            "status": ("healthy" if not reasons else "degraded"),
            "reasons": reasons,
            "authority_ready": setup.authority_ready,
            "runtime_connected": runtime_connected,
            "setup_ready": setup.setup_ready,
            "bootstrap_publish_ready": bool(setup.setup_ready and runtime_connected),
        }
        return {
            "ok": True,
            "setup": setup.model_dump(mode="json"),
            "broker": broker.model_dump(mode="json"),
            "health": health,
            "effective_status": effective,
            "last_authority_errors": last_authority_errors,
            "last_provisioning_errors": last_authority_errors,
            "reconciliation": (
                runtime_reconciler.reconciliation_status() if runtime_reconciler is not None else {"status": "unknown"}
            ),
            "bootstrap_publish": (
                runtime_reconciler.bootstrap_status() if runtime_reconciler is not None else {"published": False}
            ),
        }

    @router.get("/mqtt/health")
    async def mqtt_health_summary(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        summary = await mqtt_setup_summary(request=request, x_admin_token=x_admin_token)
        return {
            "ok": True,
            "effective_status": summary.get("effective_status", {}),
        }

    @router.post("/mqtt/setup-state")
    async def mqtt_setup_state(
        body: MqttSetupStateUpdate,
        request: Request,
        x_admin_token: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        subject = await _authorize_mqtt_request(
            request=request,
            x_admin_token=x_admin_token,
            authorization=authorization,
            key_store=key_store,
            required_scope="mqtt.setup.write",
        )
        if subject and subject != "mqtt":
            raise HTTPException(status_code=403, detail="request_subject_mismatch")
        setup = await approval.update_setup_state(body)
        broker = await approval.broker_summary()
        return {
            "ok": True,
            "setup": setup.model_dump(mode="json"),
            "broker": broker.model_dump(mode="json"),
        }

    @router.get("/mqtt/debug/acl")
    async def mqtt_debug_acl(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        compiler = acl_compiler or getattr(runtime_reconciler, "_acl_compiler", None)
        if compiler is None:
            raise HTTPException(status_code=503, detail="acl_compiler_unavailable")
        state = await state_store.get_state()
        compiled = compiler.compile(state)
        return {
            "ok": True,
            "rules": [rule.__dict__ for rule in compiled.rules],
            "acl_text": compiled.acl_text,
        }

    @router.get("/mqtt/debug/config")
    async def mqtt_debug_config(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        live_dir = None
        if runtime_reconciler is not None and hasattr(runtime_reconciler, "live_dir"):
            live_dir = runtime_reconciler.live_dir()
        if not live_dir:
            raise HTTPException(status_code=503, detail="runtime_live_dir_unavailable")
        base = Path(str(live_dir))
        files: dict[str, str] = {}
        for name in ["broker.conf", "listeners.conf", "auth.conf", "acl.conf", "acl_compiled.conf", "passwords.conf"]:
            path = base / name
            if path.exists() and path.is_file():
                files[name] = path.read_text(encoding="utf-8")
        return {"ok": True, "live_dir": str(base), "files": files}

    @router.get("/mqtt/debug/authority")
    async def mqtt_debug_authority(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        state = await state_store.get_state()
        principals = [item.model_dump(mode="json") for item in sorted(state.principals.values(), key=lambda x: x.principal_id)]
        grants = [item.model_dump(mode="json") for item in sorted(state.active_grants.values(), key=lambda x: x.addon_id)]
        return {
            "ok": True,
            "principals": principals,
            "grants": grants,
            "setup": {
                "requires_setup": state.requires_setup,
                "setup_status": state.setup_status,
                "setup_complete": state.setup_complete,
                "authority_ready": state.authority_ready,
                "setup_error": state.setup_error,
            },
        }

    @router.post("/mqtt/debug/topic-validate")
    async def mqtt_debug_topic_validate(
        body: MqttTopicValidationRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        errors = validate_topic_scopes(
            addon_id=body.addon_id,
            publish_topics=body.publish_topics,
            subscribe_topics=body.subscribe_topics,
            approved_reserved_topics=body.approved_reserved_topics,
        )
        return {"ok": len(errors) == 0, "errors": errors}

    return router
