from __future__ import annotations

from typing import Any
from pathlib import Path

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
    approval_service: MqttRegistrationApprovalService | None = None,
    acl_compiler: MqttAclCompiler | None = None,
    credential_store=None,
    runtime_reconciler=None,
) -> APIRouter:
    router = APIRouter()
    approval = approval_service or MqttRegistrationApprovalService(registry=registry, state_store=state_store)

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
        if credential_store is None:
            raise HTTPException(status_code=503, detail="credential_store_unavailable")
        rotated = bool(credential_store.rotate_principal(principal_id))
        if runtime_reconciler is not None:
            await runtime_reconciler.reconcile_authority(reason=f"rotate_credentials:{principal_id}")
        return {"ok": True, "principal_id": principal_id, "rotated": rotated}

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
