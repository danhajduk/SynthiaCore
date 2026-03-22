from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException

from .discovery import discover_backend_addons, repo_root
from .models import BackendAddon, RegisteredAddon

log = logging.getLogger("synthia.addons")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass
class AddonRegistry:
    addons: Dict[str, BackendAddon]
    errors: Dict[str, str]
    enabled: Dict[str, bool]
    registered: Dict[str, RegisteredAddon]

    def is_enabled(self, addon_id: str) -> bool:
        return self.enabled.get(addon_id, True)

    def set_enabled(self, addon_id: str, enabled: bool) -> None:
        self.enabled[addon_id] = enabled
        _save_addon_state(self.enabled)
        log.info("Addon '%s' set to %s", addon_id, "enabled" if enabled else "disabled")

    def has_addon(self, addon_id: str) -> bool:
        return addon_id in self.addons or addon_id in self.registered

    def is_platform_managed(self, addon_id: str) -> bool:
        local = self.addons.get(addon_id)
        if local is not None:
            return bool(local.meta.platform_managed)
        return False

    def list_registered(self) -> List[RegisteredAddon]:
        return sorted(self.registered.values(), key=lambda a: a.id)

    def upsert_registered(self, addon: RegisteredAddon) -> RegisteredAddon:
        now = _utcnow_iso()
        addon.tls_warning = _tls_warning_for_base_url(addon.base_url)
        if addon.tls_warning:
            log.warning("Registered addon '%s' TLS warning: %s", addon.id, addon.tls_warning)
        errors, observed_capabilities = self._check_registered_contract(addon)
        addon.contract_ok = len(errors) == 0
        addon.contract_errors = errors
        if errors:
            raise ValueError("Addon contract validation failed: " + "; ".join(errors))
        if observed_capabilities:
            addon.capabilities = observed_capabilities
        addon.health_status = "ok" if addon.contract_ok else "unhealthy"
        if addon.contract_ok:
            addon.last_seen = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            addon.last_health = {"status": addon.health_status, "last_seen": addon.last_seen}
        if not addon.discovered_at:
            addon.discovered_at = now
        addon.updated_at = now
        self.registered[addon.id] = addon
        _save_registered_addons(self.registered)
        return addon

    def delete_registered(self, addon_id: str) -> bool:
        existed = addon_id in self.registered
        if existed:
            del self.registered[addon_id]
            _save_registered_addons(self.registered)
        return existed

    def update_from_mqtt_announce(self, addon_id: str, payload: dict) -> RegisteredAddon:
        now = _utcnow_iso()
        existing = self.registered.get(addon_id)
        base_url = str(
            payload.get("base_url")
            or payload.get("api_base_url")
            or (existing.base_url if existing else "http://localhost")
        )
        addon = existing or RegisteredAddon(
            id=addon_id,
            name=str(payload.get("name") or addon_id),
            version=str(payload.get("version") or "unknown"),
            base_url=base_url,
        )
        addon.name = str(payload.get("name") or addon.name)
        addon.version = str(payload.get("version") or addon.version)
        addon.base_url = base_url
        if payload.get("ui_enabled") is not None:
            addon.ui_enabled = bool(payload.get("ui_enabled"))
        if payload.get("ui_base_url") is not None:
            addon.ui_base_url = str(payload.get("ui_base_url") or "").strip() or None
        if payload.get("ui_mode") is not None:
            addon.ui_mode = str(payload.get("ui_mode") or "").strip() or addon.ui_mode
        addon.tls_warning = _tls_warning_for_base_url(base_url)
        if addon.tls_warning:
            log.warning("MQTT announce addon '%s' TLS warning: %s", addon_id, addon.tls_warning)
        raw_caps = payload.get("capabilities")
        if isinstance(raw_caps, list):
            addon.capabilities = [str(x) for x in raw_caps]
        if payload.get("auth_mode") is not None:
            addon.auth_mode = str(payload.get("auth_mode"))
        addon.health_status = str(payload.get("health_status") or addon.health_status or "unknown")
        addon.last_seen = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        addon.last_health = {"status": addon.health_status, "last_seen": addon.last_seen}
        if not addon.discovered_at:
            addon.discovered_at = now
        addon.updated_at = now
        self.registered[addon_id] = addon
        _save_registered_addons(self.registered)
        return addon

    def update_from_mqtt_health(self, addon_id: str, payload: dict) -> RegisteredAddon:
        now = _utcnow_iso()
        existing = self.registered.get(addon_id)
        addon = existing or RegisteredAddon(
            id=addon_id,
            name=str(payload.get("name") or addon_id),
            version=str(payload.get("version") or "unknown"),
            base_url=str(payload.get("base_url") or payload.get("api_base_url") or "http://localhost"),
        )
        if payload.get("ui_enabled") is not None:
            addon.ui_enabled = bool(payload.get("ui_enabled"))
        if payload.get("ui_base_url") is not None:
            addon.ui_base_url = str(payload.get("ui_base_url") or "").strip() or None
        if payload.get("ui_mode") is not None:
            addon.ui_mode = str(payload.get("ui_mode") or "").strip() or addon.ui_mode
        addon.tls_warning = _tls_warning_for_base_url(addon.base_url)
        if addon.tls_warning:
            log.warning("MQTT health addon '%s' TLS warning: %s", addon_id, addon.tls_warning)
        if payload.get("health_status") is not None:
            addon.health_status = str(payload.get("health_status"))
        elif payload.get("status") is not None:
            addon.health_status = str(payload.get("status"))
        else:
            addon.health_status = "unknown"
        addon.last_seen = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        addon.last_health = {"status": addon.health_status, "last_seen": addon.last_seen}
        if not addon.discovered_at:
            addon.discovered_at = now
        addon.updated_at = now
        self.registered[addon_id] = addon
        _save_registered_addons(self.registered)
        return addon

    @staticmethod
    def _auth_headers(addon: RegisteredAddon) -> dict[str, str]:
        if not addon.auth_header_env:
            return {}
        secret_value = os.getenv(addon.auth_header_env, "")
        if not secret_value:
            return {}
        if addon.auth_mode == "bearer":
            return {"Authorization": f"Bearer {secret_value}"}
        if addon.auth_mode == "header" and addon.auth_header_name:
            return {addon.auth_header_name: secret_value}
        return {}

    def _check_registered_contract(self, addon: RegisteredAddon) -> tuple[list[str], list[str]]:
        base = addon.base_url.rstrip("/")
        timeout_s = max(0.1, float(addon.proxy_timeout_s))
        headers = self._auth_headers(addon)
        required_get = [
            "/api/addon/meta",
            "/api/addon/health",
            "/api/addon/capabilities",
            "/api/addon/config/effective",
        ]
        errors: list[str] = []
        observed_capabilities: list[str] = []

        with httpx.Client(timeout=httpx.Timeout(timeout_s), follow_redirects=False) as client:
            for path in required_get:
                url = f"{base}{path}"
                try:
                    r = client.get(url, headers=headers)
                    if r.status_code >= 400:
                        errors.append(f"GET {path} -> HTTP {r.status_code}")
                except Exception as e:
                    errors.append(f"GET {path} -> {type(e).__name__}")
            try:
                r = client.post(f"{base}/api/addon/config", headers=headers, json={})
                if r.status_code >= 400:
                    errors.append(f"POST /api/addon/config -> HTTP {r.status_code}")
            except Exception as e:
                errors.append(f"POST /api/addon/config -> {type(e).__name__}")

            if not errors:
                try:
                    cap_resp = client.get(f"{base}/api/addon/capabilities", headers=headers)
                    payload = cap_resp.json()
                    if isinstance(payload, dict) and isinstance(payload.get("capabilities"), list):
                        observed_capabilities = [str(x) for x in payload["capabilities"]]
                except Exception:
                    pass
        return errors, observed_capabilities

    async def register_remote(
        self,
        addon_id: str,
        *,
        base_url: str,
        name: str | None = None,
        version: str | None = None,
        ui_enabled: bool | None = None,
        ui_base_url: str | None = None,
        ui_mode: str | None = None,
    ) -> RegisteredAddon:
        now = _utcnow_iso()
        existing = self.registered.get(addon_id)
        addon = existing or RegisteredAddon(
            id=addon_id,
            name=name or addon_id,
            version=version or "unknown",
            base_url=base_url,
        )
        addon.base_url = base_url
        if ui_enabled is not None:
            addon.ui_enabled = bool(ui_enabled)
        if ui_base_url is not None:
            addon.ui_base_url = str(ui_base_url).strip() or None
        if ui_mode is not None:
            addon.ui_mode = str(ui_mode).strip() or addon.ui_mode
        addon.tls_warning = _tls_warning_for_base_url(base_url)
        if name:
            addon.name = name
        if version:
            addon.version = version
        if not addon.discovered_at:
            addon.discovered_at = now
        addon.updated_at = now

        timeout_s = max(0.1, float(addon.proxy_timeout_s))
        headers = self._auth_headers(addon)
        base = addon.base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s), follow_redirects=False) as client:
            try:
                meta_resp = await client.get(f"{base}/api/addon/meta", headers=headers)
                if meta_resp.status_code < 400:
                    payload = meta_resp.json()
                    if isinstance(payload, dict):
                        addon.name = str(payload.get("name") or addon.name)
                        addon.version = str(payload.get("version") or addon.version)
            except Exception:
                pass

            try:
                cap_resp = await client.get(f"{base}/api/addon/capabilities", headers=headers)
                if cap_resp.status_code < 400:
                    payload = cap_resp.json()
                    if isinstance(payload, dict) and isinstance(payload.get("capabilities"), list):
                        addon.capabilities = [str(x) for x in payload.get("capabilities", [])]
            except Exception:
                pass

        self.registered[addon_id] = addon
        _save_registered_addons(self.registered)
        return addon

    async def configure_registered(self, addon_id: str, config: dict[str, Any]) -> dict[str, Any]:
        addon = self.registered.get(addon_id)
        if addon is None:
            raise KeyError("addon_not_found")
        timeout_s = max(0.1, float(addon.proxy_timeout_s))
        headers = self._auth_headers(addon)
        base = addon.base_url.rstrip("/")

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s), follow_redirects=False) as client:
            resp = await client.post(f"{base}/api/addon/config", headers=headers, json=config)
        if resp.status_code >= 400:
            raise RuntimeError(f"configure_http_{resp.status_code}")

        addon.updated_at = _utcnow_iso()
        self.registered[addon_id] = addon
        _save_registered_addons(self.registered)
        payload: dict[str, Any]
        try:
            data = resp.json()
            payload = data if isinstance(data, dict) else {"result": data}
        except Exception:
            payload = {"result": resp.text}
        return payload

    async def verify_registered(self, addon_id: str) -> dict[str, Any]:
        addon = self.registered.get(addon_id)
        if addon is None:
            raise KeyError("addon_not_found")
        timeout_s = max(0.1, float(addon.proxy_timeout_s))
        headers = self._auth_headers(addon)
        base = addon.base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s), follow_redirects=False) as client:
            resp = await client.get(f"{base}/api/addon/health", headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"verify_http_{resp.status_code}")

        payload: dict[str, Any]
        try:
            data = resp.json()
            payload = data if isinstance(data, dict) else {"result": data}
        except Exception:
            payload = {"result": resp.text}

        status = str(payload.get("status") or payload.get("health_status") or "unknown")
        addon.health_status = status
        addon.last_seen = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        addon.last_health = {"status": status, "last_seen": addon.last_seen}
        addon.updated_at = _utcnow_iso()
        self.registered[addon_id] = addon
        _save_registered_addons(self.registered)
        return payload

    async def refresh_registered_health(self) -> None:
        changed = False
        for addon in self.registered.values():
            before = addon.model_dump(mode="json")
            errors, observed_capabilities = await self._check_registered_contract_async(addon)
            addon.contract_ok = len(errors) == 0
            addon.contract_errors = errors
            if observed_capabilities:
                addon.capabilities = observed_capabilities
            addon.health_status = "ok" if addon.contract_ok else "unhealthy"
            if addon.contract_ok:
                addon.last_seen = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            addon.last_health = {"status": addon.health_status, "last_seen": addon.last_seen}
            addon.updated_at = _utcnow_iso()
            if addon.model_dump(mode="json") != before:
                changed = True
        if changed:
            _save_registered_addons(self.registered)

    async def _check_registered_contract_async(self, addon: RegisteredAddon) -> tuple[list[str], list[str]]:
        base = addon.base_url.rstrip("/")
        timeout_s = max(0.1, float(addon.proxy_timeout_s))
        retries = max(0, int(addon.proxy_retries))
        headers = self._auth_headers(addon)
        required_get = [
            "/api/addon/meta",
            "/api/addon/health",
            "/api/addon/capabilities",
            "/api/addon/config/effective",
        ]
        errors: list[str] = []
        observed_capabilities: list[str] = []

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s), follow_redirects=False) as client:
            for path in required_get:
                ok = False
                last_err = ""
                for _ in range(retries + 1):
                    try:
                        r = await client.get(f"{base}{path}", headers=headers)
                        if r.status_code < 400:
                            ok = True
                            break
                        last_err = f"HTTP {r.status_code}"
                    except Exception as e:
                        last_err = type(e).__name__
                if not ok:
                    errors.append(f"GET {path} -> {last_err}")

            post_ok = False
            post_err = ""
            for _ in range(retries + 1):
                try:
                    r = await client.post(f"{base}/api/addon/config", headers=headers, json={})
                    if r.status_code < 400:
                        post_ok = True
                        break
                    post_err = f"HTTP {r.status_code}"
                except Exception as e:
                    post_err = type(e).__name__
            if not post_ok:
                errors.append(f"POST /api/addon/config -> {post_err}")

            if not errors:
                try:
                    cap_resp = await client.get(f"{base}/api/addon/capabilities", headers=headers)
                    payload = cap_resp.json()
                    if isinstance(payload, dict) and isinstance(payload.get("capabilities"), list):
                        observed_capabilities = [str(x) for x in payload["capabilities"]]
                except Exception:
                    pass
        return errors, observed_capabilities


def _state_path() -> Path:
    return repo_root() / "data" / "addons_state.json"


def _registry_path() -> Path:
    return repo_root() / "data" / "addons_registry.json"


def _load_addon_state() -> Dict[str, bool]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return {str(k): bool(v) for k, v in data.items()}
    except Exception as e:
        log.error("Failed to load addon state from %s: %s", path, e)
    return {}


def _save_addon_state(state: Dict[str, bool]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True))


def _load_registered_addons() -> Dict[str, RegisteredAddon]:
    path = _registry_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, list):
            raise ValueError("addons_registry.json must contain a JSON array")
        loaded: Dict[str, RegisteredAddon] = {}
        for item in raw:
            addon = RegisteredAddon.model_validate(item)
            loaded[addon.id] = addon
        return loaded
    except Exception as e:
        log.error("Failed to load addon registry from %s: %s", path, e)
        return {}


def _save_registered_addons(registered: Dict[str, RegisteredAddon]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [a.model_dump(mode="json") for a in sorted(registered.values(), key=lambda a: a.id)]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _tls_warning_for_base_url(base_url: str) -> str | None:
    try:
        parsed = urlparse(base_url)
    except Exception:
        return "invalid_base_url_for_tls_check"
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if not scheme:
        return "missing_url_scheme"
    if scheme == "https":
        return None
    if host in {"localhost", "127.0.0.1", "::1"}:
        return None
    return f"non_tls_base_url_for_remote_target:{base_url}"

def build_registry() -> AddonRegistry:
    log.info("Discovering backend addons")
    discovered = discover_backend_addons()
    addons: Dict[str, BackendAddon] = {}
    errors: Dict[str, str] = {}
    enabled = _load_addon_state()
    registered = _load_registered_addons()
    log.info("Discovered %d backend addons", len(discovered))

    for d in discovered:
        if d.addon is not None:
            addons[d.addon_id] = d.addon
            log.info("Loaded addon '%s' from %s", d.addon_id, d.module_path)
        else:
            errors[d.addon_id] = d.error or "Unknown error"
            log.error("Failed to load addon '%s' from %s\n%s", d.addon_id, d.module_path, errors[d.addon_id])

    changed = False
    for addon_id in addons.keys():
        if addon_id not in enabled:
            enabled[addon_id] = True
            changed = True
    if changed:
        _save_addon_state(enabled)

    return AddonRegistry(addons=addons, errors=errors, enabled=enabled, registered=registered)

def register_addons(app: FastAPI, registry: AddonRegistry) -> None:
    for addon_id, addon in registry.addons.items():
        prefix = f"/api/addons/{addon_id}"
        def _enabled_check(addon_id=addon_id):
            if not registry.is_enabled(addon_id):
                raise HTTPException(status_code=404, detail="addon_disabled")

        app.include_router(addon.router, prefix=prefix, dependencies=[Depends(_enabled_check)])

def list_addons(registry: AddonRegistry) -> List[dict]:
    out: Dict[str, dict] = {}

    for addon in registry.list_registered():
        out[addon.id] = {
            "id": addon.id,
            "name": addon.name,
            "version": addon.version,
            "description": "",
            "show_sidebar": True,
            "enabled": registry.is_enabled(addon.id),
            "base_url": addon.base_url,
            "ui_enabled": addon.ui_enabled,
            "ui_base_url": addon.ui_base_url,
            "ui_mode": addon.ui_mode,
            "capabilities": addon.capabilities,
            "health_status": addon.health_status,
            "last_health": addon.last_health,
            "last_seen": addon.last_seen,
            "discovered_at": addon.discovered_at,
            "updated_at": addon.updated_at,
            "auth_mode": addon.auth_mode,
            "tls_warning": addon.tls_warning,
            "discovery_source": "registered",
            "platform_managed": registry.is_platform_managed(addon.id),
        }

    for addon_id, addon in registry.addons.items():
        meta = addon.meta.model_dump()
        meta["enabled"] = registry.is_enabled(addon_id)
        if addon_id in out:
            # Keep local metadata authoritative while preserving remote registry details.
            out[addon_id].update(meta)
            out[addon_id]["discovery_source"] = "local+registered"
        else:
            meta.setdefault("base_url", None)
            meta.setdefault("ui_enabled", False)
            meta.setdefault("ui_base_url", None)
            meta.setdefault("ui_mode", "server")
            meta.setdefault("capabilities", [])
            meta.setdefault("health_status", "unknown")
            meta.setdefault("last_health", {})
            meta.setdefault("last_seen", None)
            meta.setdefault("discovered_at", None)
            meta.setdefault("updated_at", None)
            meta.setdefault("auth_mode", "none")
            meta.setdefault("tls_warning", None)
            meta["discovery_source"] = "local"
            out[addon_id] = meta
    return sorted(out.values(), key=lambda x: x["id"])
