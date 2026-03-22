from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.addons.registry import AddonRegistry
from app.addons.install_sessions import InstallSessionsStore
from app.system.events import PlatformEventService
from app.system.security import redact_secrets
from app.system.settings.store import SettingsStore
from app.system.services.store import ServiceCatalogStore

log = logging.getLogger("synthia.mqtt")


MQTT_SUBSCRIPTIONS = [
    ("#", 0),
    ("hexe/core/mqtt/info", 1),
    ("hexe/addons/+/announce", 1),
    ("hexe/addons/+/health", 1),
    ("hexe/services/+/catalog", 1),
    ("hexe/policy/grants/+", 1),
    ("hexe/policy/revocations/+", 1),
    ("$SYS/broker/#", 0),
    ("$SYS/broker/clients/connected", 0),
    ("$SYS/broker/clients/disconnected", 0),
]

_GENERIC_TOPIC_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MessageListener = Callable[[str, dict[str, Any], bool], Awaitable[None] | None]


@dataclass
class MqttConfig:
    mode: str
    host: str
    port: int
    username: str | None
    password: str | None
    keepalive_s: int
    tls_enabled: bool
    client_id: str


@dataclass
class MessageListenerRegistration:
    listener_id: str
    topic_filter: str
    callback: MessageListener


class MqttManager:
    def __init__(
        self,
        settings_store: SettingsStore,
        registry: AddonRegistry,
        service_catalog_store: ServiceCatalogStore,
        install_sessions_store: InstallSessionsStore | None = None,
        events: PlatformEventService | None = None,
        observability_store=None,
        enabled: bool = True,
    ) -> None:
        self._settings = settings_store
        self._registry = registry
        self._service_catalogs = service_catalog_store
        self._install_sessions = install_sessions_store
        self._events = events
        self._observability = observability_store
        self._enabled = enabled
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: Any = None
        self._config: MqttConfig | None = None
        self._connected = False
        self._last_error: str | None = None
        self._last_message_at: str | None = None
        self._message_count = 0
        self._connection_count = 0
        self._auth_failures = 0
        self._reconnect_spikes = 0
        self._last_connected_monotonic: float | None = None
        self._principal_runtime: dict[str, dict[str, Any]] = {}
        self._runtime_sessions: dict[str, dict[str, Any]] = {}
        self._sys_clients_connected: int | None = None
        self._sys_clients_disconnected: int | None = None
        self._session_idle_timeout_s = int(os.getenv("SYNTHIA_MQTT_SESSION_IDLE_TIMEOUT_S", "300"))
        self._broker_metrics: dict[str, Any] = {
            "broker_uptime": None,
            "connected_clients": None,
            "message_rate": None,
            "dropped_messages": None,
            "retained_messages": None,
            "_counter_total": None,
            "_counter_at": None,
        }
        self._principal_traffic_windows: dict[str, dict[str, Any]] = {}
        self._topic_activity: dict[str, dict[str, Any]] = {}
        self._node_runtime_state: dict[str, dict[str, Any]] = {}
        self._integration_state_path = str(
            os.getenv("MQTT_INTEGRATION_STATE_PATH", os.path.join(os.getcwd(), "var", "mqtt_integration_state.json"))
        ).strip()
        self._topic_scopes_by_principal: dict[str, list[str]] = {}
        self._topic_scopes_mtime: float | None = None
        self._runtime_rate_last_count = 0
        self._runtime_rate_last_at = 0.0
        self._error_count = 0
        self._stats_history: deque[dict[str, Any]] = deque(maxlen=50000)
        self._stats_retention_s = 24 * 60 * 60
        self._message_listeners: dict[str, MessageListenerRegistration] = {}
        self._message_listener_counter = 0

    async def start(self) -> None:
        if not self._enabled:
            self._last_error = "mqtt_disabled"
            self._connected = False
            return
        self._loop = asyncio.get_running_loop()
        await self.restart()

    async def stop(self) -> None:
        client = self._client
        self._client = None
        self._connected = False
        if client is not None:
            try:
                await asyncio.to_thread(client.loop_stop)
                await asyncio.to_thread(client.disconnect)
            except Exception as e:
                self._last_error = f"stop_failed:{type(e).__name__}"

    async def restart(self) -> None:
        if not self._enabled:
            await self.stop()
            self._last_error = "mqtt_disabled"
            self._connected = False
            return
        await self.stop()
        cfg = await self._load_config()
        self._config = cfg
        try:
            self._client = await asyncio.to_thread(self._build_and_connect_client, cfg)
            self._last_error = None
        except Exception as e:
            self._connected = False
            self._last_error = f"connect_failed:{type(e).__name__}"
            self._error_count += 1
            self._record_stats_sample()
            log.exception("MQTT restart failed")

    async def status(self) -> dict[str, Any]:
        cfg = self._config
        return {
            "ok": True,
            "enabled": self._enabled,
            "connected": self._connected,
            "mode": cfg.mode if cfg else None,
            "host": cfg.host if cfg else None,
            "port": cfg.port if cfg else None,
            "tls_enabled": cfg.tls_enabled if cfg else None,
            "subscriptions": [t for t, _ in MQTT_SUBSCRIPTIONS],
            "last_error": self._last_error,
            "last_message_at": self._last_message_at,
            "message_count": self._message_count,
            "connection_count": self._connection_count,
            "auth_failures": self._auth_failures,
            "reconnect_spikes": self._reconnect_spikes,
        }

    async def publish_test(self, topic: str | None = None, payload: dict | None = None) -> dict[str, Any]:
        if not self._enabled:
            return {"ok": False, "error": "mqtt_disabled"}
        if self._client is None:
            return {"ok": False, "error": "mqtt_not_initialized"}
        msg_topic = topic or "hexe/core/mqtt/info"
        msg_payload = payload or {
            "source": "synthia-core",
            "type": "mqtt-test",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        msg_payload = redact_secrets(msg_payload)
        result = await asyncio.to_thread(
            self._client.publish,
            msg_topic,
            json.dumps(msg_payload),
            1,
            True,
        )
        return {"ok": bool(getattr(result, "rc", 1) == 0), "topic": msg_topic, "rc": int(getattr(result, "rc", 1))}

    async def publish(self, topic: str, payload: dict[str, Any], retain: bool = True, qos: int = 1) -> dict[str, Any]:
        if not self._enabled:
            return {"ok": False, "error": "mqtt_disabled", "topic": topic}
        if self._client is None:
            return {"ok": False, "error": "mqtt_not_initialized", "topic": topic}
        safe_payload = redact_secrets(payload)
        result = await asyncio.to_thread(
            self._client.publish,
            topic,
            json.dumps(safe_payload),
            int(qos),
            bool(retain),
        )
        return {"ok": bool(getattr(result, "rc", 1) == 0), "topic": topic, "rc": int(getattr(result, "rc", 1))}

    async def principal_connection_states(self) -> dict[str, dict[str, Any]]:
        self._expire_stale_runtime_sessions()
        out: dict[str, dict[str, Any]] = {}
        for principal_id, item in sorted(self._principal_runtime.items()):
            out[principal_id] = {
                "principal_id": principal_id,
                "connected": bool(item.get("connected")),
                "connected_since": item.get("connected_since"),
                "last_seen": item.get("last_seen"),
                "session_count": int(item.get("session_count") or 0),
            }
        return out

    async def runtime_sessions(self) -> dict[str, Any]:
        self._expire_stale_runtime_sessions()
        items = []
        for _, item in sorted(
            self._runtime_sessions.items(),
            key=lambda pair: (
                str(pair[1].get("principal_id") or ""),
                str(pair[1].get("client_id") or ""),
            ),
        ):
            items.append(
                {
                    "client_id": item.get("client_id"),
                    "principal_id": item.get("principal_id"),
                    "connected": bool(item.get("connected")),
                    "connected_at": item.get("connected_at"),
                    "last_activity": item.get("last_activity"),
                    "session_count": int(item.get("session_count") or 0),
                }
            )
        return {
            "ok": True,
            "items": items,
            "broker_clients": {
                "connected": self._sys_clients_connected,
                "disconnected": self._sys_clients_disconnected,
            },
        }

    async def topic_activity(self, *, limit: int = 500) -> dict[str, Any]:
        max_items = max(1, min(int(limit), 2000))
        items = [
            {
                "topic": topic,
                "message_count": int(item.get("message_count") or 0),
                "retained_seen": bool(item.get("retained_seen", False)),
                "sources": sorted(set(item.get("sources") or {"runtime_messages"})),
                "last_seen": item.get("last_seen"),
                "_last_seen_epoch": float(item.get("_last_seen_epoch") or 0.0),
            }
            for topic, item in self._topic_activity.items()
        ]
        items = sorted(
            items,
            key=lambda row: (
                -float(row.get("_last_seen_epoch") or 0.0),
                str(row.get("topic") or ""),
            ),
        )[:max_items]
        for row in items:
            row.pop("_last_seen_epoch", None)
        return {"ok": True, "items": items}

    async def node_runtime_snapshot(self, node_id: str) -> dict[str, Any] | None:
        normalized = str(node_id or "").strip()
        if not normalized:
            return None
        snapshot = self._node_runtime_state.get(normalized)
        if snapshot is None:
            return None
        return json.loads(json.dumps(snapshot))

    async def runtime_stats_history(self, *, hours: int = 24, limit: int = 1440) -> dict[str, Any]:
        self._prune_stats_history()
        window_hours = max(1, min(int(hours), 24))
        max_items = max(1, min(int(limit), 5000))
        since_epoch = time.time() - (window_hours * 60 * 60)
        items = [
            item
            for item in self._stats_history
            if float(item.get("_ts_epoch") or 0.0) >= since_epoch
        ]
        if len(items) > max_items:
            items = items[-max_items:]
        return {
            "ok": True,
            "hours": window_hours,
            "items": [
                {
                    "timestamp": item.get("timestamp"),
                    "messages_per_second": item.get("messages_per_second"),
                    "connected_clients": item.get("connected_clients"),
                    "errors": item.get("errors"),
                }
                for item in items
            ],
        }

    async def debug_connection_config(self) -> dict[str, Any]:
        cfg = self._config or await self._load_config()
        return {
            "mode": cfg.mode,
            "host": cfg.host,
            "port": int(cfg.port),
            "username": cfg.username,
            "password": cfg.password,
            "tls_enabled": bool(cfg.tls_enabled),
            "keepalive_s": int(cfg.keepalive_s),
        }

    async def broker_health_metrics(self) -> dict[str, Any]:
        return {
            "broker_uptime": self._broker_metrics.get("broker_uptime"),
            "connected_clients": self._broker_metrics.get("connected_clients"),
            "message_rate": self._broker_metrics.get("message_rate"),
            "dropped_messages": self._broker_metrics.get("dropped_messages"),
            "retained_messages": self._broker_metrics.get("retained_messages"),
        }

    def register_message_listener(self, *, topic_filter: str, callback: MessageListener) -> str:
        normalized = str(topic_filter or "").strip()
        if not normalized:
            raise ValueError("topic_filter is required")
        self._message_listener_counter += 1
        listener_id = f"listener-{self._message_listener_counter}"
        self._message_listeners[listener_id] = MessageListenerRegistration(
            listener_id=listener_id,
            topic_filter=normalized,
            callback=callback,
        )
        return listener_id

    def unregister_message_listener(self, listener_id: str) -> bool:
        return self._message_listeners.pop(str(listener_id or "").strip(), None) is not None

    async def principal_traffic_metrics(self) -> dict[str, dict[str, Any]]:
        self._trim_principal_traffic_windows()
        out: dict[str, dict[str, Any]] = {}
        for principal_id, item in sorted(self._principal_traffic_windows.items()):
            dt = max(0.001, float(item.get("window_seconds") or 10.0))
            count = int(item.get("message_count") or 0)
            total_size = int(item.get("payload_size_total") or 0)
            out[principal_id] = {
                "messages_per_second": round(count / dt, 3),
                "payload_size": total_size,
                "topic_count": len(item.get("topics") or set()),
            }
        return out

    def _core_info_payload(self) -> dict[str, Any]:
        cfg = self._config
        return {
            "source": "synthia-core",
            "type": "core-mqtt-info",
            "heartbeat_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "broker": {
                "mode": cfg.mode if cfg else None,
                "host": cfg.host if cfg else None,
                "port": cfg.port if cfg else None,
                "tls_enabled": cfg.tls_enabled if cfg else None,
                "client_id": cfg.client_id if cfg else None,
                "username_set": bool(cfg.username) if cfg else False,
            },
        }

    def _publish_core_info_retained(self, client: Any) -> None:
        payload = redact_secrets(self._core_info_payload())
        result = client.publish("hexe/core/mqtt/info", json.dumps(payload), 1, True)
        rc = int(getattr(result, "rc", 1))
        if rc != 0:
            self._last_error = f"core_info_publish_rc:{rc}"

    async def _load_config(self) -> MqttConfig:
        mode = str((await self._settings.get("mqtt.mode")) or "local").lower()
        if mode not in {"local", "external"}:
            mode = "local"

        host_key = f"mqtt.{mode}.host"
        port_key = f"mqtt.{mode}.port"
        user_key = f"mqtt.{mode}.username"
        pass_key = f"mqtt.{mode}.password"
        tls_key = f"mqtt.{mode}.tls_enabled"

        host = str((await self._settings.get(host_key)) or ("127.0.0.1" if mode == "local" else "10.0.0.100"))
        port = int((await self._settings.get(port_key)) or 1883)
        username = (await self._settings.get(user_key)) or os.getenv("MQTT_USERNAME")
        password = (await self._settings.get(pass_key)) or os.getenv("MQTT_PASSWORD")
        tls_enabled = bool((await self._settings.get(tls_key)) or False)
        keepalive_s = int((await self._settings.get("mqtt.keepalive_s")) or 30)
        client_id = str((await self._settings.get("mqtt.client_id")) or "synthia-core")
        if mode == "local":
            # Local embedded runtime is broker-authoritative; avoid stale external settings causing auth/connect drift.
            host = str(os.getenv("SYNTHIA_MQTT_HOST", "127.0.0.1")).strip() or "127.0.0.1"
            port = int(os.getenv("SYNTHIA_MQTT_PORT", str(port)))
            username = str((await self._settings.get("mqtt.local.username")) or "").strip() or None
            password = str((await self._settings.get("mqtt.local.password")) or "")
            password = password if password else None
            local_credential = self._load_local_broker_credential()
            if local_credential is not None:
                username = local_credential.get("username") or username
                password = local_credential.get("password") or password
            tls_enabled = False
        return MqttConfig(
            mode=mode,
            host=host,
            port=port,
            username=str(username) if username else None,
            password=str(password) if password else None,
            keepalive_s=keepalive_s,
            tls_enabled=tls_enabled,
            client_id=client_id,
        )

    @staticmethod
    def _load_local_broker_credential() -> dict[str, str] | None:
        credential_path = str(
            os.getenv("MQTT_CREDENTIAL_STORE_PATH", os.path.join(os.getcwd(), "var", "mqtt_credentials.json"))
        ).strip()
        if not credential_path:
            return None
        try:
            with open(credential_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return None
        credentials = payload.get("credentials") if isinstance(payload, dict) else None
        if not isinstance(credentials, dict):
            return None
        for principal_id in ("core.runtime", "core.bootstrap", "addon:mqtt"):
            item = credentials.get(principal_id)
            if not isinstance(item, dict):
                continue
            username = str(item.get("username") or "").strip()
            password = str(item.get("password") or "")
            if username and password:
                return {"username": username, "password": password}
        return None

    def _build_and_connect_client(self, cfg: MqttConfig) -> Any:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg.client_id)
        if cfg.username:
            client.username_pw_set(cfg.username, cfg.password)
        if cfg.tls_enabled:
            client.tls_set()
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.connect_async(cfg.host, cfg.port, cfg.keepalive_s)
        client.loop_start()
        return client

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        rc = self._reason_code_value(reason_code)
        self._connected = rc == 0
        if not self._connected:
            self._last_error = f"connect_rc:{rc}"
            if rc in {4, 5, 134, 135}:
                self._auth_failures += 1
                self._error_count += 1
            self._record_observability_event(
                event_type="connection_failed",
                severity="warn",
                metadata={"reason_code": rc},
            )
            self._record_stats_sample()
            return
        now = time.monotonic()
        if self._last_connected_monotonic is not None and (now - self._last_connected_monotonic) < 60.0:
            self._reconnect_spikes += 1
        self._last_connected_monotonic = now
        self._connection_count += 1
        client_id = self._config.client_id if self._config is not None else "synthia-core"
        self._touch_principal_runtime("core.runtime", client_id=client_id)
        for topic, qos in MQTT_SUBSCRIPTIONS:
            client.subscribe(topic, qos=qos)
        self._publish_core_info_retained(client)
        self._record_observability_event(
            event_type="connection_established",
            severity="info",
            metadata={"reason_code": rc},
        )
        self._record_stats_sample()

    def _on_disconnect(self, client: Any, userdata: Any, disconnect_flags: Any, reason_code: Any, properties: Any = None) -> None:
        self._connected = False
        rc = self._reason_code_value(reason_code)
        client_id = self._config.client_id if self._config is not None else "synthia-core"
        self._mark_principal_runtime_disconnected("core.runtime", client_id=client_id)
        if rc != 0:
            self._last_error = f"disconnect_rc:{rc}"
            self._error_count += 1
            self._record_observability_event(
                event_type="disconnect_error",
                severity="warn",
                metadata={"reason_code": rc},
            )
            self._record_stats_sample()

    @staticmethod
    def _reason_code_value(reason_code: Any) -> int:
        # paho-mqtt 2.x passes ReasonCode objects on callbacks.
        if reason_code is None:
            return 0
        value = getattr(reason_code, "value", reason_code)
        try:
            return int(value)
        except Exception:
            return -1

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        self._message_count += 1
        self._last_message_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._update_runtime_message_rate()
        payload: dict[str, Any] = {}
        decoded = ""
        try:
            decoded = msg.payload.decode("utf-8", errors="replace")
            parsed = json.loads(decoded) if decoded else {}
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = {}
        topic = str(msg.topic)
        self._record_topic_activity(topic=topic, retained=bool(getattr(msg, "retain", False)))
        if topic.startswith("$SYS/broker/"):
            self._update_broker_metrics(topic=topic, payload=payload, decoded=decoded)
            return
        inferred_principal = self._infer_principal_from_topic(topic)
        inferred_tracked = False
        if inferred_principal is not None:
            inferred_client = (
                inferred_principal.split(":", 1)[1]
                if ":" in inferred_principal
                else inferred_principal
            )
            self._touch_principal_runtime(inferred_principal, client_id=inferred_client)
            self._record_principal_traffic(
                principal_id=inferred_principal,
                topic=topic,
                payload_size=len(getattr(msg, "payload", b"") or b""),
            )
            inferred_tracked = True
        parts = topic.split("/")
        if len(parts) >= 4 and parts[0] == "hexe" and parts[1] == "addons":
            addon_id = parts[2]
            event = parts[3]
            addon_principal = f"addon:{addon_id}"
            if not (inferred_tracked and inferred_principal == addon_principal):
                self._touch_principal_runtime(addon_principal, client_id=addon_principal)
                self._record_principal_traffic(
                    principal_id=addon_principal,
                    topic=topic,
                    payload_size=len(getattr(msg, "payload", b"") or b""),
                )
            if event == "announce":
                self._dispatch_registry_update(addon_id, payload, announce=True)
            elif event == "health":
                self._dispatch_registry_update(addon_id, payload, announce=False)
        if len(parts) == 4 and parts[0] == "hexe" and parts[1] == "nodes" and parts[2]:
            node_id = parts[2]
            event = parts[3]
            if event in {"lifecycle", "status"}:
                self._record_node_runtime_state(
                    node_id=node_id,
                    topic=topic,
                    payload=payload,
                    retained=bool(getattr(msg, "retain", False)),
                    event_type=event,
                )
        if len(parts) >= 4 and parts[0] == "hexe" and parts[1] == "services" and parts[3] == "catalog":
            service_name = parts[2]
            self._dispatch_service_catalog_update(service_name, payload)
        self._dispatch_message_listeners(topic=topic, payload=payload, retained=bool(getattr(msg, "retain", False)))

    def _update_runtime_message_rate(self) -> None:
        now = time.time()
        if self._runtime_rate_last_at <= 0.0:
            self._runtime_rate_last_at = now
            self._runtime_rate_last_count = int(self._message_count)
            return
        dt = now - float(self._runtime_rate_last_at)
        if dt < 1.0:
            return
        delta = max(0, int(self._message_count) - int(self._runtime_rate_last_count))
        self._broker_metrics["message_rate"] = round(float(delta) / max(dt, 0.001), 3)
        self._runtime_rate_last_at = now
        self._runtime_rate_last_count = int(self._message_count)
        self._record_stats_sample()

    @staticmethod
    def _topic_matches_filter(topic: str, topic_filter: str) -> bool:
        t_levels = [level for level in str(topic or "").split("/")]
        f_levels = [level for level in str(topic_filter or "").split("/")]
        if not t_levels or not f_levels:
            return False
        ti = 0
        fi = 0
        while fi < len(f_levels):
            token = f_levels[fi]
            if token == "#":
                return fi == len(f_levels) - 1
            if ti >= len(t_levels):
                return False
            if token != "+" and token != t_levels[ti]:
                return False
            ti += 1
            fi += 1
        return ti == len(t_levels)

    @staticmethod
    def _scope_specificity(topic_filter: str) -> tuple[int, int]:
        levels = [level for level in str(topic_filter or "").split("/") if level]
        literal_levels = [level for level in levels if level not in {"+", "#"}]
        literal_chars = sum(len(level) for level in literal_levels)
        return (len(literal_levels), literal_chars)

    def _refresh_principal_topic_scopes(self) -> None:
        path = self._integration_state_path
        if not path:
            self._topic_scopes_by_principal = {}
            self._topic_scopes_mtime = None
            return
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            self._topic_scopes_by_principal = {}
            self._topic_scopes_mtime = None
            return
        if self._topic_scopes_mtime is not None and self._topic_scopes_mtime == mtime:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            self._topic_scopes_by_principal = {}
            self._topic_scopes_mtime = mtime
            return
        principals = payload.get("principals") if isinstance(payload, dict) else None
        if not isinstance(principals, dict):
            self._topic_scopes_by_principal = {}
            self._topic_scopes_mtime = mtime
            return
        out: dict[str, list[str]] = {}
        for principal_id, row in principals.items():
            if not isinstance(row, dict):
                continue
            principal_type = str(row.get("principal_type") or "").strip().lower()
            if principal_type not in {"generic_user", "synthia_addon", "synthia_node", "system"}:
                continue
            status = str(row.get("status") or "").strip().lower()
            if status in {"revoked", "expired"}:
                continue
            scope_candidates = (
                list(row.get("publish_topics") or [])
                + list(row.get("subscribe_topics") or [])
                + list(row.get("allowed_publish_topics") or [])
                + list(row.get("allowed_subscribe_topics") or [])
                + list(row.get("allowed_topics") or [])
            )
            prefix = str(row.get("topic_prefix") or "").strip().strip("/")
            if prefix:
                scope_candidates.append(f"{prefix}/#")
            scopes = sorted({str(scope).strip() for scope in scope_candidates if str(scope).strip()})
            scoped_specific = [scope for scope in scopes if self._scope_specificity(scope)[0] > 0]
            scopes = sorted(set(scoped_specific))
            if scopes:
                out[str(principal_id)] = scopes
        self._topic_scopes_by_principal = out
        self._topic_scopes_mtime = mtime

    def _infer_principal_from_topic(self, topic: str) -> str | None:
        normalized = str(topic or "").strip()
        if not normalized:
            return None
        if normalized.startswith("$SYS/") or normalized.startswith("hexe/"):
            # Scope matching may still map hexe/* to addon/core principals; generic fallback is skipped.
            pass
        self._refresh_principal_topic_scopes()
        matches: list[tuple[tuple[int, int], str]] = []
        for principal_id, scopes in self._topic_scopes_by_principal.items():
            best_for_principal: tuple[int, int] | None = None
            for scope in scopes:
                if not self._topic_matches_filter(normalized, scope):
                    continue
                specificity = self._scope_specificity(scope)
                if best_for_principal is None or specificity > best_for_principal:
                    best_for_principal = specificity
            if best_for_principal is not None:
                matches.append((best_for_principal, principal_id))
        if matches:
            matches.sort(key=lambda row: (row[0][0], row[0][1], row[1]), reverse=True)
            top_specificity = matches[0][0]
            top_matches = [principal_id for specificity, principal_id in matches if specificity == top_specificity]
            if len(top_matches) == 1:
                return top_matches[0]
        if normalized.startswith("$SYS/") or normalized.startswith("hexe/"):
            return None
        head = normalized.split("/", 1)[0].strip()
        if not head:
            return None
        if not _GENERIC_TOPIC_SEGMENT_RE.match(head):
            return None
        principal_id = f"user:{head}"
        if not self._topic_scopes_by_principal:
            return principal_id
        if principal_id in self._topic_scopes_by_principal:
            return principal_id
        return None

    def _record_topic_activity(self, *, topic: str, retained: bool) -> None:
        normalized = str(topic or "").strip()
        if not normalized:
            return
        now = time.time()
        item = dict(self._topic_activity.get(normalized) or {})
        item["message_count"] = int(item.get("message_count") or 0) + 1
        item["retained_seen"] = bool(item.get("retained_seen") or retained)
        sources = set(item.get("sources") or {"runtime_messages"})
        sources.add("runtime_messages")
        if retained:
            sources.add("retained")
        item["sources"] = sources
        item["_last_seen_epoch"] = now
        item["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        self._topic_activity[normalized] = item

    @staticmethod
    def _normalize_node_lifecycle_state(payload: dict[str, Any]) -> str | None:
        for key in ("lifecycle_state", "state", "lifecycle", "status", "mode"):
            value = str(payload.get(key) or "").strip().lower()
            if value:
                return value
        return None

    @staticmethod
    def _normalize_node_health_status(payload: dict[str, Any]) -> str | None:
        for key in ("health_status", "status", "health", "state"):
            value = str(payload.get(key) or "").strip().lower()
            if value:
                return value
        return None

    def _record_node_runtime_state(
        self,
        *,
        node_id: str,
        topic: str,
        payload: dict[str, Any],
        retained: bool,
        event_type: str,
    ) -> None:
        normalized_node_id = str(node_id or "").strip()
        if not normalized_node_id:
            return
        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        snapshot = dict(self._node_runtime_state.get(normalized_node_id) or {})
        event_payload = {
            "topic": str(topic or "").strip(),
            "payload": dict(payload or {}),
            "received_at": now_iso,
            "retained": bool(retained),
        }
        if event_type == "lifecycle":
            lifecycle_state = self._normalize_node_lifecycle_state(payload)
            event_payload["lifecycle_state"] = lifecycle_state
            snapshot["lifecycle"] = event_payload
            snapshot["reported_lifecycle_state"] = lifecycle_state
            snapshot["last_lifecycle_report_at"] = now_iso
            snapshot["_last_lifecycle_report_epoch"] = now
        elif event_type == "status":
            health_status = self._normalize_node_health_status(payload)
            event_payload["health_status"] = health_status
            snapshot["status"] = event_payload
            snapshot["reported_health_status"] = health_status
            snapshot["last_status_report_at"] = now_iso
            snapshot["_last_status_report_epoch"] = now
        snapshot["node_id"] = normalized_node_id
        snapshot["updated_at"] = now_iso
        self._node_runtime_state[normalized_node_id] = snapshot

    @staticmethod
    def _parse_int_payload(payload: dict[str, Any], decoded: str) -> int | None:
        if isinstance(payload, dict):
            if "value" in payload:
                try:
                    return int(payload.get("value"))
                except Exception:
                    pass
        raw = str(decoded or "").strip()
        if raw:
            try:
                return int(raw)
            except Exception:
                return None
        return None

    def _touch_principal_runtime(self, principal_id: str, *, client_id: str) -> None:
        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        principal = dict(self._principal_runtime.get(principal_id) or {})
        if not bool(principal.get("connected")):
            principal["connected"] = True
            principal["connected_since"] = now_iso
            principal["session_count"] = int(principal.get("session_count") or 0) + 1
        principal["last_seen"] = now_iso
        principal["_last_seen_epoch"] = now
        self._principal_runtime[principal_id] = principal

        session = dict(self._runtime_sessions.get(client_id) or {})
        if not bool(session.get("connected")):
            session["connected"] = True
            session["connected_at"] = now_iso
            session["session_count"] = int(session.get("session_count") or 0) + 1
        session["client_id"] = client_id
        session["principal_id"] = principal_id
        session["last_activity"] = now_iso
        session["_last_activity_epoch"] = now
        self._runtime_sessions[client_id] = session

    def _mark_principal_runtime_disconnected(self, principal_id: str, *, client_id: str) -> None:
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        principal = dict(self._principal_runtime.get(principal_id) or {})
        principal["connected"] = False
        principal["last_seen"] = now_iso
        self._principal_runtime[principal_id] = principal

        session = dict(self._runtime_sessions.get(client_id) or {})
        session["client_id"] = client_id
        session["principal_id"] = principal_id
        session["connected"] = False
        session["last_activity"] = now_iso
        self._runtime_sessions[client_id] = session

    def _expire_stale_runtime_sessions(self) -> None:
        now = time.time()
        ttl = max(30, int(self._session_idle_timeout_s))
        for principal_id, principal in list(self._principal_runtime.items()):
            if principal_id == "core.runtime":
                continue
            if not bool(principal.get("connected")):
                continue
            seen_at = float(principal.get("_last_seen_epoch") or 0.0)
            if seen_at <= 0.0:
                continue
            if (now - seen_at) <= ttl:
                continue
            updated = dict(principal)
            updated["connected"] = False
            self._principal_runtime[principal_id] = updated
        for client_id, session in list(self._runtime_sessions.items()):
            if client_id == (self._config.client_id if self._config is not None else "synthia-core"):
                continue
            if not bool(session.get("connected")):
                continue
            seen_at = float(session.get("_last_activity_epoch") or 0.0)
            if seen_at <= 0.0:
                continue
            if (now - seen_at) <= ttl:
                continue
            updated = dict(session)
            updated["connected"] = False
            self._runtime_sessions[client_id] = updated

    def _record_principal_traffic(self, *, principal_id: str, topic: str, payload_size: int) -> None:
        now = time.time()
        window = dict(self._principal_traffic_windows.get(principal_id) or {})
        started_at = float(window.get("window_started_at") or 0.0)
        if started_at <= 0.0 or (now - started_at) > 10.0:
            window = {
                "window_started_at": now,
                "window_seconds": 10.0,
                "message_count": 0,
                "payload_size_total": 0,
                "topics": set(),
                "updated_at": now,
            }
        window["message_count"] = int(window.get("message_count") or 0) + 1
        window["payload_size_total"] = int(window.get("payload_size_total") or 0) + max(0, int(payload_size))
        topics = set(window.get("topics") or set())
        topics.add(str(topic))
        window["topics"] = topics
        window["updated_at"] = now
        self._principal_traffic_windows[principal_id] = window

    def _trim_principal_traffic_windows(self) -> None:
        now = time.time()
        keep_seconds = 60.0
        for principal_id, item in list(self._principal_traffic_windows.items()):
            updated_at = float(item.get("updated_at") or 0.0)
            if updated_at <= 0.0:
                continue
            if (now - updated_at) <= keep_seconds:
                continue
            self._principal_traffic_windows.pop(principal_id, None)

    def _update_broker_metrics(self, *, topic: str, payload: dict[str, Any], decoded: str) -> None:
        value_int = self._parse_int_payload(payload, decoded)
        value_raw = str(decoded or "").strip()
        if topic == "$SYS/broker/clients/connected":
            self._sys_clients_connected = value_int
            self._broker_metrics["connected_clients"] = value_int
            self._record_stats_sample()
            return
        if topic == "$SYS/broker/clients/disconnected":
            self._sys_clients_disconnected = value_int
            self._record_stats_sample()
            return
        if topic == "$SYS/broker/uptime":
            self._broker_metrics["broker_uptime"] = value_raw or None
            self._record_stats_sample()
            return
        lowered = topic.lower()
        if "dropped" in lowered and value_int is not None:
            self._broker_metrics["dropped_messages"] = value_int
        if "retained" in lowered and ("count" in lowered or "messages" in lowered) and value_int is not None:
            self._broker_metrics["retained_messages"] = value_int
        if lowered.endswith("/messages/received") or lowered.endswith("/messages/sent"):
            next_total = (value_int if value_int is not None else 0)
            if lowered.endswith("/messages/sent"):
                self._broker_metrics["_messages_sent"] = next_total
            else:
                self._broker_metrics["_messages_received"] = next_total
            # message_rate is derived from observed runtime traffic in _update_runtime_message_rate().
            # Avoid deriving from $SYS cumulative counters here because alternating received/sent samples can
            # produce unrealistic spikes when sampled with very small dt.
        self._record_stats_sample()

    def _record_stats_sample(self) -> None:
        now = time.time()
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        sample = {
            "_ts_epoch": now,
            "timestamp": timestamp,
            "messages_per_second": self._broker_metrics.get("message_rate"),
            "connected_clients": self._broker_metrics.get("connected_clients"),
            "errors": int(self._error_count),
        }
        last = self._stats_history[-1] if self._stats_history else None
        if isinstance(last, dict):
            # Avoid high-frequency duplicates with no metric changes.
            if (
                sample.get("messages_per_second") == last.get("messages_per_second")
                and sample.get("connected_clients") == last.get("connected_clients")
                and sample.get("errors") == last.get("errors")
                and (now - float(last.get("_ts_epoch") or 0.0)) < 1.0
            ):
                return
        self._stats_history.append(sample)
        self._prune_stats_history()

    def _prune_stats_history(self) -> None:
        cutoff = time.time() - float(self._stats_retention_s)
        while self._stats_history:
            first = self._stats_history[0]
            if float(first.get("_ts_epoch") or 0.0) >= cutoff:
                break
            self._stats_history.popleft()

    def _dispatch_registry_update(self, addon_id: str, payload: dict[str, Any], announce: bool) -> None:
        loop = self._loop
        if loop is None:
            return

        async def _run() -> None:
            try:
                prior = self._registry.registered.get(addon_id)
                prior_health = str(prior.health_status).lower() if prior is not None else "unknown"
                if announce:
                    addon = self._registry.update_from_mqtt_announce(addon_id, payload)
                    if self._install_sessions is not None:
                        self._install_sessions.mark_discovered(addon_id)
                    if self._events is not None:
                        await self._events.emit(
                            event_type="addon_started",
                            source="mqtt.announce",
                            payload={
                                "addon_id": addon_id,
                                "health_status": addon.health_status,
                                "version": addon.version,
                                "base_url": addon.base_url,
                            },
                        )
                else:
                    addon = self._registry.update_from_mqtt_health(addon_id, payload)
                    current_health = str(addon.health_status).lower()
                    failed_states = {"failed", "error", "unhealthy", "down"}
                    started_states = {"ok", "healthy", "running", "up"}
                    if self._events is not None and current_health != prior_health:
                        if current_health in failed_states:
                            await self._events.emit(
                                event_type="addon_failed",
                                source="mqtt.health",
                                payload={"addon_id": addon_id, "health_status": addon.health_status},
                            )
                        elif current_health in started_states:
                            await self._events.emit(
                                event_type="addon_started",
                                source="mqtt.health",
                                payload={"addon_id": addon_id, "health_status": addon.health_status},
                            )
            except Exception:
                log.exception("Failed to apply MQTT addon update")

        asyncio.run_coroutine_threadsafe(_run(), loop)

    def _dispatch_service_catalog_update(self, service_name: str, payload: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return

        async def _run() -> None:
            try:
                await self._service_catalogs.upsert_catalog(service_name, payload)
            except Exception:
                log.exception("Failed to apply MQTT service catalog update")

        asyncio.run_coroutine_threadsafe(_run(), loop)

    def _record_observability_event(self, *, event_type: str, severity: str, metadata: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or self._observability is None:
            return

        async def _run() -> None:
            try:
                await self._observability.append_event(
                    event_type=event_type,
                    source="mqtt_manager",
                    severity=severity,
                    metadata=metadata,
                )
            except Exception:
                log.exception("Failed to record MQTT observability event")

        asyncio.run_coroutine_threadsafe(_run(), loop)

    def _dispatch_message_listeners(self, *, topic: str, payload: dict[str, Any], retained: bool) -> None:
        loop = self._loop
        if loop is None:
            return
        for registration in list(self._message_listeners.values()):
            if not self._topic_matches_filter(topic, registration.topic_filter):
                continue

            async def _run(callback: MessageListener = registration.callback) -> None:
                try:
                    result = callback(topic, payload, retained)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    log.exception("Failed to apply MQTT message listener for topic=%s", topic)

            asyncio.run_coroutine_threadsafe(_run(), loop)
