from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit, urlunsplit

UiMode = Literal["spa", "server"]


def normalize_ui_base_url(raw: str | None) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("ui_base_url_invalid")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def normalize_ui_mode(raw: str | None, default: UiMode = "spa") -> UiMode:
    text = str(raw or "").strip().lower()
    if text in {"spa", "server"}:
        return text
    return default


def normalize_ui_health_endpoint(raw: str | None) -> str | None:
    return normalize_ui_base_url(raw)


def derive_node_api_base_url(
    *,
    api_base_url: str | None = None,
    ui_base_url: str | None = None,
    requested_ui_endpoint: str | None = None,
    requested_hostname: str | None = None,
) -> str | None:
    base = normalize_ui_base_url(api_base_url)
    if base is not None:
        return base
    fallback = normalize_ui_base_url(ui_base_url)
    if fallback is None:
        fallback = normalize_ui_base_url(requested_ui_endpoint)
    if fallback is not None:
        parsed = urlsplit(fallback)
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    host = str(requested_hostname or "").strip()
    if not host:
        return None
    if host.startswith("http://") or host.startswith("https://"):
        parsed_host = urlsplit(host)
        if parsed_host.scheme in {"http", "https"} and parsed_host.netloc:
            return urlunsplit((parsed_host.scheme, parsed_host.netloc, "", "", ""))
    parsed_host = urlsplit(f"http://{host}")
    if parsed_host.netloc:
        return urlunsplit((parsed_host.scheme, parsed_host.netloc, "", "", ""))
    return None


def derive_node_ui_metadata(
    *,
    requested_ui_endpoint: str | None,
    requested_hostname: str | None,
    ui_enabled: bool | None = None,
    ui_base_url: str | None = None,
    ui_mode: str | None = None,
    ui_health_endpoint: str | None = None,
) -> tuple[bool, str | None, UiMode, str | None]:
    base = normalize_ui_base_url(ui_base_url)
    if base is None:
        base = normalize_ui_base_url(requested_ui_endpoint)
    if base is None:
        host = str(requested_hostname or "").strip()
        if host:
            if host.startswith("http://") or host.startswith("https://"):
                base = normalize_ui_base_url(host)
            else:
                base = normalize_ui_base_url(f"http://{host}")
    enabled = bool(base) if ui_enabled is None else bool(ui_enabled)
    if not enabled:
        return False, None, normalize_ui_mode(ui_mode), normalize_ui_health_endpoint(ui_health_endpoint)
    return True, base, normalize_ui_mode(ui_mode), normalize_ui_health_endpoint(ui_health_endpoint)


def derive_addon_ui_metadata(
    *,
    base_url: str | None,
    ui_enabled: bool | None = None,
    ui_base_url: str | None = None,
    ui_mode: str | None = None,
) -> tuple[bool, str | None, UiMode]:
    base = normalize_ui_base_url(ui_base_url or base_url)
    enabled = bool(base) if ui_enabled is None else bool(ui_enabled)
    if not enabled:
        return False, None, normalize_ui_mode(ui_mode)
    return True, base, normalize_ui_mode(ui_mode, default="server")
