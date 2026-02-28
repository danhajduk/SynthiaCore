from __future__ import annotations

from typing import Any


SECRET_HINTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "credential",
    "auth_header",
)


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            lk = str(k).lower()
            if any(h in lk for h in SECRET_HINTS):
                out[str(k)] = "***REDACTED***"
            else:
                out[str(k)] = redact_secrets(v)
        return out
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    return value
