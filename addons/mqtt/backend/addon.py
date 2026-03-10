from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.addons.models import AddonMeta, BackendAddon

router = APIRouter()
_config: dict[str, Any] = {}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("", response_class=HTMLResponse)
def addon_ui_root() -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Synthia MQTT</title></head>"
        "<body>"
        "<h1>Synthia MQTT</h1>"
        "<p>Embedded platform-managed MQTT addon is loaded.</p>"
        "<p>Use Core Settings and MQTT APIs for configuration and operations.</p>"
        "</body></html>"
    )


@router.get("/api/addon/meta")
def addon_meta() -> dict[str, Any]:
    return {
        "id": "mqtt",
        "name": "Synthia MQTT",
        "version": "0.1.0",
        "description": "Platform-managed embedded MQTT infrastructure addon",
    }


@router.get("/api/addon/health")
def addon_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "embedded_platform",
        "platform_managed": True,
        "checked_at": _utcnow_iso(),
    }


@router.get("/api/addon/capabilities")
def addon_capabilities() -> dict[str, Any]:
    return {
        "capabilities": [
            "mqtt.broker_runtime",
            "mqtt.authority",
            "mqtt.bootstrap",
        ],
        "platform_managed": True,
    }


@router.get("/api/addon/config/effective")
def addon_effective_config() -> dict[str, Any]:
    return {
        "platform_managed": True,
        "config": dict(_config),
    }


@router.post("/api/addon/config")
def addon_config_update(body: dict[str, Any]) -> dict[str, Any]:
    if isinstance(body, dict):
        _config.update(body)
    return {
        "ok": True,
        "platform_managed": True,
        "updated_at": _utcnow_iso(),
        "config": dict(_config),
    }


addon = BackendAddon(
    meta=AddonMeta(
        id="mqtt",
        name="Synthia MQTT",
        version="0.1.0",
        description="Platform-managed embedded MQTT infrastructure addon.",
        show_sidebar=False,
        platform_managed=True,
        capabilities=["mqtt.broker_runtime", "mqtt.authority", "mqtt.bootstrap"],
    ),
    router=router,
)
