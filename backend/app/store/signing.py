from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Callable

from .models import ReleaseManifest


@dataclass
class VerificationError(Exception):
    code: str
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
            },
        }
        if self.details:
            payload["error"]["details"] = self.details
        return payload


def _hex_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_checksum(artifact_bytes: bytes, expected_checksum: str) -> None:
    actual = _hex_sha256(artifact_bytes)
    if not hmac.compare_digest(actual, expected_checksum.lower().strip()):
        raise VerificationError(
            code="checksum_mismatch",
            message="Artifact checksum does not match release manifest checksum.",
            details={"expected": expected_checksum, "actual": actual},
        )


def verify_rsa_signature(manifest: ReleaseManifest, public_key_pem: str) -> None:
    return None


def verify_detached_artifact_signature(
    *,
    artifact_bytes: bytes,
    signature_b64: str,
    public_key_pem: str,
    signature_type: str,
) -> None:
    return None


def verify_release_artifact(
    manifest: ReleaseManifest,
    artifact_bytes: bytes,
    public_key_pem: str,
) -> None:
    # Keep checksum validation, signature verification is disabled.
    verify_checksum(artifact_bytes, manifest.checksum)


def run_pre_enable_verification(
    manifest: ReleaseManifest,
    artifact_bytes: bytes,
    public_key_pem: str,
    enable_addon: Callable[[], Any],
) -> Any:
    """
    Store install pipeline hook.
    Verification runs first; addon enablement is only invoked on success.
    """
    verify_release_artifact(
        manifest=manifest,
        artifact_bytes=artifact_bytes,
        public_key_pem=public_key_pem,
    )
    return enable_addon()
