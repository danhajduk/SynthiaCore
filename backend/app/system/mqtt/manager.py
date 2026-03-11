from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from app.addons.registry import AddonRegistry
from app.addons.install_sessions import InstallSessionsStore
from app.system.events import PlatformEventService
from app.system.security import redact_secrets
from app.system.settings.store import SettingsStore
from app.system.services.store import ServiceCatalogStore

log = logging.getLogger("synthia.mqtt")


MQTT_SUBSCRIPTIONS = [
    ("synthia/core/mqtt/info", 1),
    ("synthia/addons/+/announce", 1),
    ("synthia/addons/+/health", 1),
    ("synthia/services/+/catalog", 1),
    ("synthia/policy/grants/+", 1),
    ("synthia/policy/revocations/+", 1),
    ("$SYS/broker/clients/connected", 0),
    ("$SYS/broker/clients/disconnected", 0),
]


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
        msg_topic = topic or "synthia/core/mqtt/info"
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
        result = client.publish("synthia/core/mqtt/info", json.dumps(payload), 1, True)
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
        for principal_id in ("addon:mqtt", "core.runtime", "core.bootstrap"):
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
            self._record_observability_event(
                event_type="connection_failed",
                severity="warn",
                metadata={"reason_code": rc},
            )
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

    def _on_disconnect(self, client: Any, userdata: Any, disconnect_flags: Any, reason_code: Any, properties: Any = None) -> None:
        self._connected = False
        rc = self._reason_code_value(reason_code)
        client_id = self._config.client_id if self._config is not None else "synthia-core"
        self._mark_principal_runtime_disconnected("core.runtime", client_id=client_id)
        if rc != 0:
            self._last_error = f"disconnect_rc:{rc}"
            self._record_observability_event(
                event_type="disconnect_error",
                severity="warn",
                metadata={"reason_code": rc},
            )

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
        if topic == "$SYS/broker/clients/connected":
            self._sys_clients_connected = self._parse_int_payload(payload, decoded)
            return
        if topic == "$SYS/broker/clients/disconnected":
            self._sys_clients_disconnected = self._parse_int_payload(payload, decoded)
            return
        parts = topic.split("/")
        if len(parts) >= 4 and parts[0] == "synthia" and parts[1] == "addons":
            addon_id = parts[2]
            event = parts[3]
            self._touch_principal_runtime(f"addon:{addon_id}", client_id=f"addon:{addon_id}")
            if event == "announce":
                self._dispatch_registry_update(addon_id, payload, announce=True)
            elif event == "health":
                self._dispatch_registry_update(addon_id, payload, announce=False)
        if len(parts) >= 4 and parts[0] == "synthia" and parts[1] == "services" and parts[3] == "catalog":
            service_name = parts[2]
            self._dispatch_service_catalog_update(service_name, payload)

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
