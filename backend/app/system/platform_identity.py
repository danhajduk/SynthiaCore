from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from typing import Any

from app.system.settings.store import SettingsStore


DEFAULT_PLATFORM_NAME = "Hexe AI"
DEFAULT_PLATFORM_SHORT = "Hexe"
DEFAULT_PLATFORM_DOMAIN = "hexe-ai.com"
DEFAULT_PLATFORM_CORE_NAME = "Hexe Core"
DEFAULT_PLATFORM_SUPERVISOR_NAME = "Hexe Supervisor"
DEFAULT_PLATFORM_NODES_NAME = "Hexe Nodes"
DEFAULT_PLATFORM_ADDONS_NAME = "Hexe Addons"
DEFAULT_PLATFORM_DOCS_NAME = "Hexe Docs"
DEFAULT_LEGACY_INTERNAL_NAMESPACE = "synthia"
DEFAULT_CORE_ID = "hexe-core"
CORE_ID_PATTERN = re.compile(r"^[a-f0-9]{16}$")


def is_valid_core_id(value: str) -> bool:
    return bool(CORE_ID_PATTERN.fullmatch(str(value or "").strip().lower()))


def generate_core_id() -> str:
    return secrets.token_hex(8)


def derive_public_ui_hostname(core_id: str, platform_domain: str) -> str:
    normalized = str(core_id or "").strip().lower()
    domain = str(platform_domain or "").strip().lower()
    if not is_valid_core_id(normalized):
        raise ValueError("core_id_invalid")
    if not domain:
        raise ValueError("platform_domain_invalid")
    return f"{normalized}.{domain}"


def derive_public_api_hostname(core_id: str, platform_domain: str) -> str:
    normalized = str(core_id or "").strip().lower()
    domain = str(platform_domain or "").strip().lower()
    if not is_valid_core_id(normalized):
        raise ValueError("core_id_invalid")
    if not domain:
        raise ValueError("platform_domain_invalid")
    return f"api.{normalized}.{domain}"


@dataclass(frozen=True)
class PlatformIdentity:
    core_id: str
    platform_name: str
    platform_short: str
    platform_domain: str
    core_name: str
    supervisor_name: str
    nodes_name: str
    addons_name: str
    docs_name: str
    legacy_internal_namespace: str
    legacy_compatibility_note: str
    public_ui_hostname: str
    public_api_hostname: str

    def to_dict(self) -> dict[str, str]:
        return {
            "core_id": self.core_id,
            "platform_name": self.platform_name,
            "platform_short": self.platform_short,
            "platform_domain": self.platform_domain,
            "core_name": self.core_name,
            "supervisor_name": self.supervisor_name,
            "nodes_name": self.nodes_name,
            "addons_name": self.addons_name,
            "docs_name": self.docs_name,
            "legacy_internal_namespace": self.legacy_internal_namespace,
            "legacy_compatibility_note": self.legacy_compatibility_note,
            "public_ui_hostname": self.public_ui_hostname,
            "public_api_hostname": self.public_api_hostname,
        }


class PlatformNamingService:
    def __init__(self, identity: PlatformIdentity) -> None:
        self._identity = identity

    @property
    def identity(self) -> PlatformIdentity:
        return self._identity

    def platform(self) -> str:
        return self._identity.platform_name

    def platform_short(self) -> str:
        return self._identity.platform_short

    def platform_domain(self) -> str:
        return self._identity.platform_domain

    def core(self) -> str:
        return self._identity.core_name

    def supervisor(self) -> str:
        return self._identity.supervisor_name

    def nodes(self) -> str:
        return self._identity.nodes_name

    def addons(self) -> str:
        return self._identity.addons_name

    def docs(self) -> str:
        return self._identity.docs_name

    def legacy_namespace(self) -> str:
        return self._identity.legacy_internal_namespace

    def compatibility_note(self) -> str:
        return self._identity.legacy_compatibility_note

    def core_id(self) -> str:
        return self._identity.core_id

    def public_ui_hostname(self) -> str:
        return self._identity.public_ui_hostname

    def public_api_hostname(self) -> str:
        return self._identity.public_api_hostname


async def load_platform_identity(settings_store: SettingsStore | None = None) -> PlatformIdentity:
    values: dict[str, Any] = {}
    if settings_store is not None:
        try:
            values = await settings_store.get_all()
            await _ensure_core_identity_settings(settings_store, values)
            values = await settings_store.get_all()
        except Exception:
            values = {}
    return platform_identity_from_values(values)


async def load_platform_naming(settings_store: SettingsStore | None = None) -> PlatformNamingService:
    return PlatformNamingService(await load_platform_identity(settings_store))


def platform_identity_from_values(values: dict[str, Any] | None = None) -> PlatformIdentity:
    data = values if isinstance(values, dict) else {}
    platform_name = _pick_text(
        data.get("platform.name"),
        os.getenv("PLATFORM_NAME"),
        DEFAULT_PLATFORM_NAME,
    )
    platform_short = _pick_text(
        data.get("platform.short"),
        os.getenv("PLATFORM_SHORT"),
        DEFAULT_PLATFORM_SHORT,
    )
    platform_domain = _pick_text(
        data.get("platform.domain"),
        os.getenv("PLATFORM_DOMAIN"),
        DEFAULT_PLATFORM_DOMAIN,
    )
    core_name = _pick_text(
        data.get("app.name"),
        data.get("platform.core_name"),
        os.getenv("PLATFORM_CORE_NAME"),
        DEFAULT_PLATFORM_CORE_NAME if platform_short == DEFAULT_PLATFORM_SHORT else f"{platform_short} Core",
    )
    supervisor_name = _pick_text(
        data.get("platform.supervisor_name"),
        os.getenv("PLATFORM_SUPERVISOR_NAME"),
        DEFAULT_PLATFORM_SUPERVISOR_NAME if platform_short == DEFAULT_PLATFORM_SHORT else f"{platform_short} Supervisor",
    )
    nodes_name = _pick_text(
        data.get("platform.nodes_name"),
        os.getenv("PLATFORM_NODES_NAME"),
        DEFAULT_PLATFORM_NODES_NAME if platform_short == DEFAULT_PLATFORM_SHORT else f"{platform_short} Nodes",
    )
    addons_name = _pick_text(
        data.get("platform.addons_name"),
        os.getenv("PLATFORM_ADDONS_NAME"),
        DEFAULT_PLATFORM_ADDONS_NAME if platform_short == DEFAULT_PLATFORM_SHORT else f"{platform_short} Addons",
    )
    docs_name = _pick_text(
        data.get("platform.docs_name"),
        os.getenv("PLATFORM_DOCS_NAME"),
        DEFAULT_PLATFORM_DOCS_NAME if platform_short == DEFAULT_PLATFORM_SHORT else f"{platform_short} Docs",
    )
    legacy_internal_namespace = _pick_text(
        data.get("platform.legacy_internal_namespace"),
        os.getenv("PLATFORM_LEGACY_INTERNAL_NAMESPACE"),
        DEFAULT_LEGACY_INTERNAL_NAMESPACE,
    )
    legacy_compatibility_note = _pick_text(
        data.get("platform.legacy_compatibility_note"),
        os.getenv("PLATFORM_LEGACY_COMPATIBILITY_NOTE"),
        f"Internal legacy identifiers may still use `{legacy_internal_namespace}` during migration.",
    )
    core_id = _pick_core_id(
        data.get("platform.core_id"),
        data.get("core.id"),
        os.getenv("SYNTHIA_CORE_ID"),
    )
    public_ui_hostname = derive_public_ui_hostname(core_id, platform_domain)
    public_api_hostname = derive_public_api_hostname(core_id, platform_domain)
    return PlatformIdentity(
        core_id=core_id,
        platform_name=platform_name,
        platform_short=platform_short,
        platform_domain=platform_domain,
        core_name=core_name,
        supervisor_name=supervisor_name,
        nodes_name=nodes_name,
        addons_name=addons_name,
        docs_name=docs_name,
        legacy_internal_namespace=legacy_internal_namespace,
        legacy_compatibility_note=legacy_compatibility_note,
        public_ui_hostname=public_ui_hostname,
        public_api_hostname=public_api_hostname,
    )


def default_platform_identity() -> PlatformIdentity:
    return platform_identity_from_values({})


def default_platform_naming() -> PlatformNamingService:
    return PlatformNamingService(default_platform_identity())


def _pick_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _pick_core_id(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip().lower()
        if not text:
            continue
        if is_valid_core_id(text):
            return text
        if text == DEFAULT_CORE_ID:
            return generate_core_id()
    return generate_core_id()


async def _ensure_core_identity_settings(settings_store: SettingsStore, values: dict[str, Any]) -> None:
    current = str(values.get("platform.core_id") or values.get("core.id") or "").strip().lower()
    if is_valid_core_id(current):
        return
    env_value = str(os.getenv("SYNTHIA_CORE_ID", "")).strip().lower()
    if is_valid_core_id(env_value):
        core_id = env_value
    else:
        core_id = generate_core_id()
    await settings_store.set("platform.core_id", core_id)
    await settings_store.set("core.id", core_id)
