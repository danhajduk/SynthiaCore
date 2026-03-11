from __future__ import annotations

from typing import Any
from pathlib import Path
import re
import socket
import asyncio
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.admin import require_admin_token
from app.system.auth import ServiceTokenError, ServiceTokenKeyStore, validate_claims, verify_hs256

from .acl_compiler import MqttAclCompiler
from .approval import MqttRegistrationApprovalService
from .integration_models import MqttRegistrationRequest, MqttSetupStateUpdate
from .integration_state import MqttIntegrationStateStore
from .manager import MqttManager
from .topic_families import is_platform_reserved_topic
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


class MqttUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str | None = "generated"
    topic_prefix: str | None = None
    access_mode: str = "private"
    allowed_topics: list[str] = Field(default_factory=list)
    allowed_publish_topics: list[str] = Field(default_factory=list)
    allowed_subscribe_topics: list[str] = Field(default_factory=list)


class MqttUserUpdateRequest(BaseModel):
    topic_prefix: str | None = None
    access_mode: str | None = None
    allowed_topics: list[str] = Field(default_factory=list)
    allowed_publish_topics: list[str] = Field(default_factory=list)
    allowed_subscribe_topics: list[str] = Field(default_factory=list)


class MqttGenericUserGrantUpdateRequest(BaseModel):
    publish_topics: list[str] = Field(default_factory=list)
    subscribe_topics: list[str] = Field(default_factory=list)
    notes: str | None = None


class MqttNoisyActionRequest(BaseModel):
    reason: str | None = None


class MqttRuntimeMitigationRequest(BaseModel):
    principal_id: str = Field(..., min_length=1)
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


class MqttDebugSubscribeRequest(BaseModel):
    topic_filter: str = Field(..., min_length=1)
    qos: int = Field(default=0, ge=0, le=2)
    timeout_s: int = Field(default=300, ge=30, le=300)


class MqttDebugUnsubscribeRequest(BaseModel):
    subscription_id: str = Field(..., min_length=1)


class MqttDebugPublishRequest(BaseModel):
    topic: str = Field(..., min_length=1)
    payload: Any = Field(default_factory=dict)
    qos: int = Field(default=0, ge=0, le=2)
    retain: bool = False


_MQTT_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
_EXPECTED_CORE_PRINCIPALS: tuple[str, ...] = (
    "core.bootstrap",
    "core.runtime",
    "core.scheduler",
    "core.supervisor",
    "core.telemetry",
)


def _normalize_generic_username(value: str) -> str:
    return str(value or "").strip().lower()


def _valid_generic_username(value: str) -> bool:
    return bool(_MQTT_USERNAME_RE.fullmatch(value))


def _normalize_topic_prefix(value: str | None) -> str:
    raw = str(value or "").strip().strip("/")
    while "//" in raw:
        raw = raw.replace("//", "/")
    return raw


def _compute_generic_scopes(
    *,
    username: str,
    topic_prefix: str,
    access_mode: str,
    allowed_topics: list[str],
    allowed_publish_topics: list[str],
    allowed_subscribe_topics: list[str],
) -> tuple[str, list[str], list[str], list[str], list[str], list[str]]:
    def _normalized_unique(topics: list[str]) -> list[str]:
        return sorted({str(item).strip() for item in topics if str(item).strip()})

    def _is_valid_topic_filter(topic: str) -> bool:
        if not topic:
            return False
        if "//" in topic:
            return False
        levels = topic.split("/")
        for idx, level in enumerate(levels):
            if "#" in level:
                if level != "#" or idx != len(levels) - 1:
                    return False
            if "+" in level and level != "+":
                return False
        return True

    def _validate_topic_filters(topics: list[str]) -> None:
        invalid = [topic for topic in topics if not _is_valid_topic_filter(topic)]
        if invalid:
            raise HTTPException(status_code=400, detail=f"topic_pattern_invalid:{invalid[0]}")

    mode = str(access_mode or "private").strip().lower()
    if mode not in {"private", "custom", "non_reserved", "admin"}:
        raise HTTPException(status_code=400, detail="access_mode_invalid")
    if mode == "private":
        scope = f"{topic_prefix}/#"
        return mode, [scope], [scope], [], [], []
    if mode == "custom":
        merged_topics = _normalized_unique(allowed_topics)
        publish_topics = _normalized_unique(allowed_publish_topics or merged_topics)
        subscribe_topics = _normalized_unique(allowed_subscribe_topics or merged_topics)
        if not publish_topics or not subscribe_topics:
            raise HTTPException(status_code=400, detail="allowed_topics_required")
        _validate_topic_filters(publish_topics)
        _validate_topic_filters(subscribe_topics)
        all_custom_topics = sorted({*publish_topics, *subscribe_topics})
        return mode, publish_topics, subscribe_topics, all_custom_topics, publish_topics, subscribe_topics
    # non_reserved/admin both grant broad publish/subscribe; ACL enforcement determines reserved boundaries.
    return mode, ["#"], ["#"], [], [], []


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
    debug_subscriptions: dict[str, dict[str, Any]] = {}

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

    async def _debug_stop_subscription(subscription_id: str) -> bool:
        item = debug_subscriptions.pop(subscription_id, None)
        if item is None:
            return False
        client = item.get("client")
        if client is not None:
            try:
                await asyncio.to_thread(client.disconnect)
            except Exception:
                pass
            try:
                await asyncio.to_thread(client.loop_stop)
            except Exception:
                pass
        task = item.get("timeout_task")
        if task is not None and hasattr(task, "cancel"):
            try:
                task.cancel()
            except Exception:
                pass
        return True

    async def _debug_timeout_worker(subscription_id: str, timeout_s: int) -> None:
        try:
            await asyncio.sleep(max(30, int(timeout_s)))
            await _debug_stop_subscription(subscription_id)
        except asyncio.CancelledError:
            return
        except Exception:
            return

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

    def _runtime_bootstrap_callable():
        if runtime_reconciler is None:
            return None
        fn = getattr(runtime_reconciler, "ensure_bootstrap_published", None)
        if callable(fn):
            return fn
        return None

    async def _invoke_reconcile(
        *,
        reason: str,
        update_setup_state: bool | None = None,
        publish_bootstrap: bool | None = None,
    ) -> Any:
        reconcile_fn = _runtime_reconciler_callable()
        if reconcile_fn is None:
            return None
        kwargs: dict[str, Any] = {"reason": reason}
        if update_setup_state is not None:
            kwargs["update_setup_state"] = bool(update_setup_state)
        if publish_bootstrap is not None:
            kwargs["publish_bootstrap"] = bool(publish_bootstrap)
        try:
            return await reconcile_fn(**kwargs)
        except TypeError:
            return await reconcile_fn(reason=reason)

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
        reconcile_update_setup_state: bool | None = None,
        reconcile_publish_bootstrap: bool | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        existing = dict(reconcile_payload or {})
        status = await runtime.ensure_running()
        payload = _runtime_status_payload(status)
        if payload.get("healthy"):
            return payload, existing
        reason = str(payload.get("degraded_reason") or "").strip().lower()
        if reason.startswith("config_missing") and _runtime_reconciler_callable() is not None:
            retried = await _invoke_reconcile(
                reason=retry_reason,
                update_setup_state=reconcile_update_setup_state,
                publish_bootstrap=reconcile_publish_bootstrap,
            )
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

    @router.post("/debug/subscribe")
    async def mqtt_debug_subscribe(
        body: MqttDebugSubscribeRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        cfg_fn = getattr(manager, "debug_connection_config", None)
        if not callable(cfg_fn):
            raise HTTPException(status_code=503, detail="debug_connection_unavailable")
        cfg = await cfg_fn()
        topic_filter = str(body.topic_filter or "").strip()
        if not topic_filter:
            raise HTTPException(status_code=400, detail="topic_filter_required")
        try:
            import paho.mqtt.client as mqtt
        except Exception:
            raise HTTPException(status_code=503, detail="mqtt_client_library_unavailable")
        subscription_id = str(uuid4())
        queue: deque[dict[str, Any]] = deque(maxlen=500)
        lock = threading.Lock()
        now = datetime.now(timezone.utc)
        timeout_s = max(30, int(body.timeout_s))
        expires_at = now + timedelta(seconds=timeout_s)
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"synthia-debug-{subscription_id[:12]}")
        username = str(cfg.get("username") or "").strip()
        password = str(cfg.get("password") or "")
        if username:
            client.username_pw_set(username, password or None)
        if bool(cfg.get("tls_enabled")):
            client.tls_set()

        def _on_message(_client, _userdata, msg) -> None:
            payload_text = msg.payload.decode("utf-8", errors="replace")
            with lock:
                queue.append(
                    {
                        "topic": str(msg.topic),
                        "payload": payload_text,
                        "qos": int(getattr(msg, "qos", 0)),
                        "retain": bool(getattr(msg, "retain", False)),
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }
                )

        client.on_message = _on_message
        try:
            client.connect_async(str(cfg.get("host") or "127.0.0.1"), int(cfg.get("port") or 1883), int(cfg.get("keepalive_s") or 30))
            client.loop_start()
            client.subscribe(topic_filter, qos=int(body.qos))
        except Exception as exc:
            try:
                client.loop_stop()
            except Exception:
                pass
            raise HTTPException(status_code=400, detail=f"debug_subscribe_failed:{type(exc).__name__}")

        timeout_task = asyncio.create_task(_debug_timeout_worker(subscription_id, timeout_s))
        debug_subscriptions[subscription_id] = {
            "client": client,
            "queue": queue,
            "lock": lock,
            "topic_filter": topic_filter,
            "qos": int(body.qos),
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "timeout_task": timeout_task,
        }
        await _audit_runtime_action(
            action="debug_subscribe",
            status="ok",
            payload={"subscription_id": subscription_id, "topic_filter": topic_filter, "qos": int(body.qos)},
        )
        return {
            "ok": True,
            "subscription_id": subscription_id,
            "topic_filter": topic_filter,
            "qos": int(body.qos),
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

    @router.get("/debug/subscribe/{subscription_id}/messages")
    async def mqtt_debug_subscribe_messages(
        subscription_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
        limit: int = 100,
    ):
        require_admin_token(x_admin_token, request)
        item = debug_subscriptions.get(subscription_id)
        if item is None:
            raise HTTPException(status_code=404, detail="debug_subscription_not_found")
        queue = item.get("queue")
        lock = item.get("lock")
        if queue is None or lock is None:
            raise HTTPException(status_code=404, detail="debug_subscription_not_found")
        max_items = max(1, min(int(limit), 500))
        with lock:
            items = list(queue)[-max_items:]
        return {
            "ok": True,
            "subscription_id": subscription_id,
            "topic_filter": item.get("topic_filter"),
            "qos": item.get("qos"),
            "expires_at": item.get("expires_at"),
            "items": items,
        }

    @router.post("/debug/unsubscribe")
    async def mqtt_debug_unsubscribe(
        body: MqttDebugUnsubscribeRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        stopped = await _debug_stop_subscription(body.subscription_id)
        if not stopped:
            raise HTTPException(status_code=404, detail="debug_subscription_not_found")
        await _audit_runtime_action(
            action="debug_unsubscribe",
            status="ok",
            payload={"subscription_id": body.subscription_id},
        )
        return {"ok": True, "subscription_id": body.subscription_id}

    @router.post("/debug/publish")
    async def mqtt_debug_publish(
        body: MqttDebugPublishRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        topic = str(body.topic or "").strip()
        if not topic:
            raise HTTPException(status_code=400, detail="topic_required")
        if is_platform_reserved_topic(topic):
            await _audit_runtime_action(
                action="debug_publish",
                status="warn",
                message="reserved_topic_publish_forbidden",
                payload={"topic": topic},
            )
            raise HTTPException(status_code=400, detail="reserved_topic_publish_forbidden")
        payload = body.payload
        if isinstance(payload, dict):
            safe_payload = payload
        else:
            safe_payload = {"value": payload}
        result = await manager.publish(topic, safe_payload, retain=bool(body.retain), qos=int(body.qos))
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=str(result.get("error") or "debug_publish_failed"))
        await _audit_runtime_action(
            action="debug_publish",
            status="ok",
            payload={"topic": topic, "qos": int(body.qos), "retain": bool(body.retain)},
        )
        return {
            "ok": True,
            "topic": topic,
            "qos": int(body.qos),
            "retain": bool(body.retain),
            "rc": int(result.get("rc") or 0),
        }

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
            if _runtime_reconciler_callable() is not None:
                reconcile_result = await _invoke_reconcile(
                    reason="api_setup_apply_local",
                    update_setup_state=False,
                    publish_bootstrap=False,
                )
                reconcile_payload = _reconcile_payload(reconcile_result)
            runtime_payload, reconcile_payload = await _ensure_runtime_with_config_retry(
                runtime,
                retry_reason="api_setup_apply_local_config_missing",
                reconcile_payload=reconcile_payload,
                reconcile_update_setup_state=False,
                reconcile_publish_bootstrap=False,
            )
            bootstrap_fn = _runtime_bootstrap_callable()
            if bool(runtime_payload.get("healthy")) and bootstrap_fn is not None:
                await bootstrap_fn()
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
    @router.get("/runtime/health")
    async def mqtt_runtime_health(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        runtime = _runtime_required()
        runtime_status = await runtime.health_check()
        health = await _manager_status_safe()
        metrics_fn = getattr(manager, "broker_health_metrics", None)
        broker_metrics = await metrics_fn() if callable(metrics_fn) else {}
        return {
            "ok": True,
            "action": "health",
            "runtime": _runtime_status_payload(runtime_status),
            "health": health,
            "broker_metrics": broker_metrics if isinstance(broker_metrics, dict) else {},
        }

    @router.get("/mqtt/runtime/sessions")
    @router.get("/runtime/sessions")
    async def mqtt_runtime_sessions(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        sessions_fn = getattr(manager, "runtime_sessions", None)
        if not callable(sessions_fn):
            return {"ok": True, "items": [], "broker_clients": {"connected": None, "disconnected": None}}
        payload = await sessions_fn()
        if not isinstance(payload, dict):
            return {"ok": True, "items": [], "broker_clients": {"connected": None, "disconnected": None}}
        return {
            "ok": bool(payload.get("ok", True)),
            "items": list(payload.get("items") or []),
            "broker_clients": dict(payload.get("broker_clients") or {"connected": None, "disconnected": None}),
        }

    async def _runtime_mitigation_action(
        *,
        principal_id: str,
        action: str,
        reason: str | None,
    ) -> dict[str, Any]:
        result = await approval.apply_noisy_client_action(principal_id, action, reason=reason)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=str(result.get("error") or "runtime_mitigation_failed"))
        await _audit_runtime_action(
            action=f"runtime_{action}",
            status="ok",
            payload={"principal_id": principal_id, "reason": reason},
        )
        return result

    @router.post("/runtime/disconnect")
    async def mqtt_runtime_disconnect(
        body: MqttRuntimeMitigationRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        return await _runtime_mitigation_action(
            principal_id=body.principal_id,
            action="quarantine",
            reason=body.reason or "runtime_disconnect",
        )

    @router.post("/runtime/block")
    async def mqtt_runtime_block(
        body: MqttRuntimeMitigationRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        return await _runtime_mitigation_action(
            principal_id=body.principal_id,
            action="block",
            reason=body.reason or "runtime_block",
        )

    @router.post("/runtime/throttle")
    async def mqtt_runtime_throttle(
        body: MqttRuntimeMitigationRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        return await _runtime_mitigation_action(
            principal_id=body.principal_id,
            action="throttle",
            reason=body.reason or "runtime_throttle",
        )

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
        if _runtime_reconciler_callable() is not None:
            reconcile_result = await _invoke_reconcile(
                reason="api_runtime_init",
                update_setup_state=False,
                publish_bootstrap=False,
            )
        reconcile_payload = _reconcile_payload(reconcile_result)
        runtime_payload, reconcile_payload = await _ensure_runtime_with_config_retry(
            runtime,
            retry_reason="api_runtime_init_config_missing",
            reconcile_payload=reconcile_payload,
            reconcile_update_setup_state=False,
            reconcile_publish_bootstrap=False,
        )
        bootstrap_fn = _runtime_bootstrap_callable()
        if bool(runtime_payload.get("healthy")) and bootstrap_fn is not None:
            await bootstrap_fn()
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
        items = await approval.list_principals()
        runtime_map: dict[str, dict[str, Any]] = {}
        runtime_fn = getattr(manager, "principal_connection_states", None)
        if callable(runtime_fn):
            try:
                payload = await runtime_fn()
                if isinstance(payload, dict):
                    runtime_map = payload
            except Exception:
                runtime_map = {}
        for item in items:
            principal_id = str(item.get("principal_id") or "")
            state = runtime_map.get(principal_id) or {}
            item["runtime_connection"] = {
                "connected": bool(state.get("connected", False)),
                "connected_since": state.get("connected_since"),
                "last_seen": state.get("last_seen"),
                "session_count": int(state.get("session_count") or 0),
            }
        return {"ok": True, "items": items}

    def _principal_permissions_payload(item: dict[str, Any]) -> dict[str, Any]:
        allowed_publish_topics = list(item.get("allowed_publish_topics") or [])
        allowed_subscribe_topics = list(item.get("allowed_subscribe_topics") or [])
        allowed_topics = list(item.get("allowed_topics") or [])
        if not allowed_publish_topics and allowed_topics:
            allowed_publish_topics = list(allowed_topics)
        if not allowed_subscribe_topics and allowed_topics:
            allowed_subscribe_topics = list(allowed_topics)
        return {
            "principal_id": str(item.get("principal_id") or ""),
            "principal_type": str(item.get("principal_type") or ""),
            "access_mode": str(item.get("access_mode") or "private"),
            "allowed_topics": sorted({*allowed_publish_topics, *allowed_subscribe_topics}),
            "allowed_publish_topics": allowed_publish_topics,
            "allowed_subscribe_topics": allowed_subscribe_topics,
            "publish_topics": list(item.get("publish_topics") or []),
            "subscribe_topics": list(item.get("subscribe_topics") or []),
            "approved_reserved_topics": list(item.get("approved_reserved_topics") or []),
        }

    def _principal_last_seen_payload(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "principal_id": str(item.get("principal_id") or ""),
            "last_seen": (
                item.get("noisy_updated_at")
                or item.get("updated_at")
                or item.get("last_activated_at")
                or item.get("last_revoked_at")
            ),
            "updated_at": item.get("updated_at"),
            "last_activated_at": item.get("last_activated_at"),
            "last_revoked_at": item.get("last_revoked_at"),
            "status": item.get("status"),
        }

    @router.get("/mqtt/principals/{principal_id}")
    @router.get("/principals/{principal_id}")
    async def mqtt_principal_details(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        item = await approval.get_principal(principal_id)
        if item is None:
            raise HTTPException(status_code=404, detail="principal_not_found")
        return {"ok": True, "principal": item}

    @router.get("/mqtt/principals/{principal_id}/permissions")
    @router.get("/principals/{principal_id}/permissions")
    async def mqtt_principal_permissions(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        item = await approval.get_principal(principal_id)
        if item is None:
            raise HTTPException(status_code=404, detail="principal_not_found")
        return {"ok": True, "permissions": _principal_permissions_payload(item)}

    @router.get("/mqtt/principals/{principal_id}/last-seen")
    @router.get("/principals/{principal_id}/last_seen")
    async def mqtt_principal_last_seen(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        item = await approval.get_principal(principal_id)
        if item is None:
            raise HTTPException(status_code=404, detail="principal_not_found")
        return {"ok": True, "last_seen": _principal_last_seen_payload(item)}

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

    async def _apply_principal_alias_action(principal_id: str, action: str, reason: str) -> dict[str, Any]:
        result = await approval.apply_principal_action(principal_id, action, reason=reason)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=str(result.get("error") or "principal_action_failed"))
        await _audit_runtime_action(
            action=f"principal_{action}",
            status="ok",
            payload={"principal_id": principal_id, "reason": reason},
        )
        return result

    @router.post("/mqtt/principals/{principal_id}/activate")
    @router.post("/principals/{principal_id}/activate")
    async def mqtt_principal_activate(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        return await _apply_principal_alias_action(principal_id, "activate", "api_activate")

    @router.post("/mqtt/principals/{principal_id}/disable")
    @router.post("/principals/{principal_id}/disable")
    async def mqtt_principal_disable(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        return await _apply_principal_alias_action(principal_id, "probation", "api_disable")

    @router.post("/mqtt/principals/{principal_id}/revoke")
    @router.post("/principals/{principal_id}/revoke")
    async def mqtt_principal_revoke(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        return await _apply_principal_alias_action(principal_id, "revoke", "api_revoke")

    @router.post("/mqtt/principals/{principal_id}/rotate-password")
    @router.post("/principals/{principal_id}/rotate_password")
    async def mqtt_principal_rotate_password(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        result = await approval.apply_noisy_client_action(
            principal_id,
            "rotate_credentials",
            reason="api_principal_rotate_password",
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=str(result.get("error") or "rotate_credentials_failed"))
        credential = credential_store.get_principal_credential(principal_id) if credential_store is not None else None
        if credential_store is not None:
            state = await state_store.get_state()
            if credential is None and principal_id in state.principals:
                credential_store.render_password_file(state)
                credential = credential_store.get_principal_credential(principal_id)
        await _audit_runtime_action(
            action="principal_rotate_password",
            status="ok",
            payload={"principal_id": principal_id, "rotated": bool(result.get("rotated"))},
        )
        return {
            "ok": True,
            "principal_id": principal_id,
            "rotated": bool(result.get("rotated")),
            "password": (credential or {}).get("password"),
            "username": (credential or {}).get("username"),
        }

    @router.delete("/mqtt/principals/{principal_id}")
    @router.delete("/principals/{principal_id}")
    async def mqtt_principal_delete(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        principal = await approval.get_principal(principal_id)
        if principal is None:
            raise HTTPException(status_code=404, detail="principal_not_found")
        principal_type = str(principal.get("principal_type") or "")
        if principal_type == "system":
            raise HTTPException(status_code=400, detail="system_principal_delete_not_allowed")
        if principal_type != "generic_user":
            raise HTTPException(status_code=400, detail="principal_delete_not_supported")
        result = await approval.delete_generic_user(principal_id)
        if not result.get("ok"):
            error = str(result.get("error") or "principal_delete_failed")
            if error == "principal_not_found":
                raise HTTPException(status_code=404, detail=error)
            raise HTTPException(status_code=400, detail=error)
        await _audit_runtime_action(
            action="principal_delete",
            status="ok",
            payload={"principal_id": principal_id},
        )
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

    @router.post("/mqtt/users")
    async def mqtt_users_create(
        body: MqttUserCreateRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        normalized_username = _normalize_generic_username(body.username)
        if not _valid_generic_username(normalized_username):
            raise HTTPException(status_code=400, detail="username_invalid")
        expected_prefix = f"external/{normalized_username}"
        requested_prefix = _normalize_topic_prefix(body.topic_prefix)
        if requested_prefix and requested_prefix != expected_prefix:
            raise HTTPException(status_code=400, detail="topic_prefix_invalid")
        topic_prefix = requested_prefix or expected_prefix
        mode, publish_topics, subscribe_topics, allowed_topics, allowed_publish_topics, allowed_subscribe_topics = _compute_generic_scopes(
            username=normalized_username,
            topic_prefix=topic_prefix,
            access_mode=body.access_mode,
            allowed_topics=body.allowed_topics,
            allowed_publish_topics=body.allowed_publish_topics,
            allowed_subscribe_topics=body.allowed_subscribe_topics,
        )
        principal_id = f"user:{normalized_username}"
        requested_password = str(body.password or "generated").strip()
        result = await approval.create_or_update_generic_user(
            principal_id=principal_id,
            logical_identity=f"generic:{normalized_username}",
            username=normalized_username,
            topic_prefix=topic_prefix,
            access_mode=mode,
            allowed_topics=allowed_topics,
            allowed_publish_topics=allowed_publish_topics,
            allowed_subscribe_topics=allowed_subscribe_topics,
            publish_topics=publish_topics,
            subscribe_topics=subscribe_topics,
            notes="generic_user_api_create",
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=str(result.get("error") or "generic_user_create_failed"))
        password_mode = "generated"
        if requested_password and requested_password.lower() != "generated":
            password_mode = "provided"
            if credential_store is not None:
                override_ok = bool(
                    credential_store.set_principal_password(
                        principal_id=principal_id,
                        principal_type="generic_user",
                        username=normalized_username,
                        password=requested_password,
                    )
                )
                if override_ok:
                    result = await approval.create_or_update_generic_user(
                        principal_id=principal_id,
                        logical_identity=f"generic:{normalized_username}",
                        username=normalized_username,
                        topic_prefix=topic_prefix,
                        access_mode=mode,
                        allowed_topics=allowed_topics,
                        allowed_publish_topics=allowed_publish_topics,
                        allowed_subscribe_topics=allowed_subscribe_topics,
                        publish_topics=publish_topics,
                        subscribe_topics=subscribe_topics,
                        notes="generic_user_api_create",
                    )
                    if not result.get("ok"):
                        raise HTTPException(status_code=400, detail=str(result.get("error") or "generic_user_create_failed"))
        principal = result.get("principal") if isinstance(result.get("principal"), dict) else {}
        credential = credential_store.get_principal_credential(principal_id) if credential_store is not None else None
        if credential is None and credential_store is not None:
            state = await state_store.get_state()
            credential_store.render_password_file(state)
            credential = credential_store.get_principal_credential(principal_id)
        return {
            "ok": True,
            "principal": principal,
            "username": normalized_username,
            "topic_prefix": topic_prefix,
            "scope": publish_topics[0] if publish_topics else None,
            "access_mode": mode,
            "allowed_topics": allowed_topics,
            "allowed_publish_topics": allowed_publish_topics,
            "allowed_subscribe_topics": allowed_subscribe_topics,
            "password_mode": password_mode,
            "password": (credential or {}).get("password"),
        }

    @router.patch("/mqtt/users/{principal_id}")
    async def mqtt_users_update(
        principal_id: str,
        body: MqttUserUpdateRequest,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        prefix = _normalize_topic_prefix(body.topic_prefix)
        result = await approval.update_generic_user_topic_prefix(
            principal_id=principal_id,
            topic_prefix=prefix,
            access_mode=body.access_mode,
            allowed_topics=body.allowed_topics,
            allowed_publish_topics=body.allowed_publish_topics,
            allowed_subscribe_topics=body.allowed_subscribe_topics,
        )
        if not result.get("ok"):
            error = str(result.get("error") or "generic_user_update_failed")
            if error == "principal_not_found":
                raise HTTPException(status_code=404, detail=error)
            raise HTTPException(status_code=400, detail=error)
        return result

    @router.delete("/mqtt/users/{principal_id}")
    async def mqtt_users_delete(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        result = await approval.delete_generic_user(principal_id)
        if not result.get("ok"):
            error = str(result.get("error") or "generic_user_delete_failed")
            if error == "principal_not_found":
                raise HTTPException(status_code=404, detail=error)
            raise HTTPException(status_code=400, detail=error)
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

    @router.post("/mqtt/users/{principal_id}/rotate")
    async def mqtt_user_rotate_credentials(
        principal_id: str,
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        result = await approval.apply_noisy_client_action(principal_id, "rotate_credentials", reason="api_users_rotate")
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=str(result.get("error") or "rotate_credentials_failed"))
        rotated = bool(result.get("rotated"))
        credential = credential_store.get_principal_credential(principal_id) if credential_store is not None else None
        if credential_store is not None:
            state = await state_store.get_state()
            if credential is None and principal_id in state.principals:
                credential_store.render_password_file(state)
                credential = credential_store.get_principal_credential(principal_id)
            if not rotated and credential is not None:
                rotated = True
        return {
            "ok": True,
            "principal_id": principal_id,
            "rotated": rotated,
            "password": (credential or {}).get("password"),
            "username": (credential or {}).get("username"),
        }

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
        principal: str | None = None,
        action: str | None = None,
    ):
        require_admin_token(x_admin_token, request)
        if audit_store is None:
            return {"ok": True, "items": []}
        list_events = getattr(audit_store, "list_events", None)
        if not callable(list_events):
            return {"ok": True, "items": []}
        try:
            items = await list_events(limit=limit, principal=principal, action=action)
        except TypeError:
            items = await list_events(limit=limit)
        return {"ok": True, "items": items}

    @router.get("/mqtt/setup-summary")
    async def mqtt_setup_summary(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        setup = await approval.setup_summary()
        broker = await approval.broker_summary()
        health = await manager.status()
        grants = await approval.list_grants()
        principal_items = await approval.list_principals()
        present_principal_ids = {str(item.get("principal_id") or "") for item in principal_items}
        missing_core_principals = [principal_id for principal_id in _EXPECTED_CORE_PRINCIPALS if principal_id not in present_principal_ids]
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
        if missing_core_principals:
            reasons.append("missing_core_principals")
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
            "core_principals": {
                "expected": list(_EXPECTED_CORE_PRINCIPALS),
                "missing": missing_core_principals,
                "ok": len(missing_core_principals) == 0,
            },
        }

    @router.get("/mqtt/health")
    async def mqtt_health_summary(request: Request, x_admin_token: str | None = Header(default=None)):
        require_admin_token(x_admin_token, request)
        summary = await mqtt_setup_summary(request=request, x_admin_token=x_admin_token)
        return {
            "ok": True,
            "effective_status": summary.get("effective_status", {}),
        }

    @router.post("/mqtt/bootstrap/publish")
    async def mqtt_bootstrap_publish(
        request: Request,
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin_token(x_admin_token, request)
        publish_fn = _runtime_bootstrap_callable()
        if publish_fn is None:
            raise HTTPException(status_code=503, detail="runtime_bootstrap_unavailable")
        published = bool(await publish_fn(force=True))
        if published:
            await _audit_runtime_action(
                action="bootstrap_publish",
                status="ok",
                payload={"published": True},
            )
        else:
            await _audit_runtime_action(
                action="bootstrap_publish",
                status="error",
                message="publish_failed",
                payload={"published": False},
            )
        return {"ok": published, "published": published}

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
