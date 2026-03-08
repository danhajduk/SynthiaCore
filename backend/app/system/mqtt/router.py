from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.admin import require_admin_token
from app.system.auth import ServiceTokenError, ServiceTokenKeyStore, validate_claims, verify_hs256

from .approval import MqttRegistrationApprovalService
from .integration_models import MqttRegistrationRequest, MqttSetupStateUpdate
from .integration_state import MqttIntegrationStateStore
from .manager import MqttManager


class MqttTestRequest(BaseModel):
    topic: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


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
) -> APIRouter:
    router = APIRouter()
    approval = MqttRegistrationApprovalService(registry=registry, state_store=state_store)

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

    @router.get("/mqtt/setup-summary")
    async def mqtt_setup_summary(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        setup = await approval.setup_summary()
        broker = await approval.broker_summary()
        return {
            "ok": True,
            "setup": setup.model_dump(mode="json"),
            "broker": broker.model_dump(mode="json"),
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

    return router
