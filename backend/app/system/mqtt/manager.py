from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from app.addons.registry import AddonRegistry
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
    ) -> None:
        self._settings = settings_store
        self._registry = registry
        self._service_catalogs = service_catalog_store
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: Any = None
        self._config: MqttConfig | None = None
        self._connected = False
        self._last_error: str | None = None
        self._last_message_at: str | None = None
        self._message_count = 0

    async def start(self) -> None:
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
            "connected": self._connected,
            "mode": cfg.mode if cfg else None,
            "host": cfg.host if cfg else None,
            "port": cfg.port if cfg else None,
            "tls_enabled": cfg.tls_enabled if cfg else None,
            "subscriptions": [t for t, _ in MQTT_SUBSCRIPTIONS],
            "last_error": self._last_error,
            "last_message_at": self._last_message_at,
            "message_count": self._message_count,
        }

    async def publish_test(self, topic: str | None = None, payload: dict | None = None) -> dict[str, Any]:
        if self._client is None:
            return {"ok": False, "error": "mqtt_not_initialized"}
        msg_topic = topic or "synthia/core/mqtt/info"
        msg_payload = payload or {
            "source": "synthia-core",
            "type": "mqtt-test",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        result = await asyncio.to_thread(
            self._client.publish,
            msg_topic,
            json.dumps(msg_payload),
            1,
            True,
        )
        return {"ok": bool(getattr(result, "rc", 1) == 0), "topic": msg_topic, "rc": int(getattr(result, "rc", 1))}

    async def publish(self, topic: str, payload: dict[str, Any], retain: bool = True, qos: int = 1) -> dict[str, Any]:
        if self._client is None:
            return {"ok": False, "error": "mqtt_not_initialized", "topic": topic}
        result = await asyncio.to_thread(
            self._client.publish,
            topic,
            json.dumps(payload),
            int(qos),
            bool(retain),
        )
        return {"ok": bool(getattr(result, "rc", 1) == 0), "topic": topic, "rc": int(getattr(result, "rc", 1))}

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
        self._connected = int(reason_code) == 0
        if not self._connected:
            self._last_error = f"connect_rc:{int(reason_code)}"
            return
        for topic, qos in MQTT_SUBSCRIPTIONS:
            client.subscribe(topic, qos=qos)

    def _on_disconnect(self, client: Any, userdata: Any, disconnect_flags: Any, reason_code: Any, properties: Any = None) -> None:
        self._connected = False
        if int(reason_code) != 0:
            self._last_error = f"disconnect_rc:{int(reason_code)}"

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        self._message_count += 1
        self._last_message_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload: dict[str, Any] = {}
        try:
            decoded = msg.payload.decode("utf-8", errors="replace")
            parsed = json.loads(decoded) if decoded else {}
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = {}
        topic = str(msg.topic)
        parts = topic.split("/")
        if len(parts) >= 4 and parts[0] == "synthia" and parts[1] == "addons":
            addon_id = parts[2]
            event = parts[3]
            if event == "announce":
                self._dispatch_registry_update(addon_id, payload, announce=True)
            elif event == "health":
                self._dispatch_registry_update(addon_id, payload, announce=False)
        if len(parts) >= 4 and parts[0] == "synthia" and parts[1] == "services" and parts[3] == "catalog":
            service_name = parts[2]
            self._dispatch_service_catalog_update(service_name, payload)

    def _dispatch_registry_update(self, addon_id: str, payload: dict[str, Any], announce: bool) -> None:
        loop = self._loop
        if loop is None:
            return

        async def _run() -> None:
            try:
                if announce:
                    self._registry.update_from_mqtt_announce(addon_id, payload)
                else:
                    self._registry.update_from_mqtt_health(addon_id, payload)
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
