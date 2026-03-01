from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

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


def _build_signature_payload(manifest: ReleaseManifest) -> bytes:
    # Canonical payload to avoid signature drift across platforms.
    payload = {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "core_min_version": manifest.core_min_version,
        "core_max_version": manifest.core_max_version,
        "dependencies": manifest.dependencies,
        "conflicts": manifest.conflicts,
        "checksum": manifest.checksum,
        "publisher_id": manifest.publisher_id,
        "permissions": manifest.permissions,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _normalize_public_key_pem(public_key_pem: str) -> str:
    text = str(public_key_pem or "").strip()
    if not text:
        return ""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    if "\\n" in text or "\\r" in text:
        text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    return text


def verify_checksum(artifact_bytes: bytes, expected_checksum: str) -> None:
    actual = _hex_sha256(artifact_bytes)
    if not hmac.compare_digest(actual, expected_checksum.lower().strip()):
        raise VerificationError(
            code="checksum_mismatch",
            message="Artifact checksum does not match release manifest checksum.",
            details={"expected": expected_checksum, "actual": actual},
        )


def verify_rsa_signature(manifest: ReleaseManifest, public_key_pem: str) -> None:
    signature_b64 = manifest.signature.signature.strip()
    if not signature_b64:
        raise VerificationError(
            code="signature_missing",
            message="Release manifest signature is missing.",
        )
    normalized_public_key_pem = _normalize_public_key_pem(public_key_pem)
    if not normalized_public_key_pem:
        raise VerificationError(
            code="public_key_missing",
            message="Publisher public key is missing.",
        )
    if manifest.signature.publisher_id != manifest.publisher_id:
        raise VerificationError(
            code="publisher_mismatch",
            message="Signature publisher_id does not match manifest publisher_id.",
            details={
                "signature_publisher_id": manifest.signature.publisher_id,
                "manifest_publisher_id": manifest.publisher_id,
            },
        )

    try:
        key = serialization.load_pem_public_key(normalized_public_key_pem.encode("utf-8"))
    except Exception as exc:
        raise VerificationError(
            code="public_key_invalid",
            message="Publisher public key is not a valid PEM RSA public key.",
        ) from exc

    if not isinstance(key, rsa.RSAPublicKey):
        raise VerificationError(
            code="public_key_not_rsa",
            message="Only RSA public keys are supported for addon package verification.",
        )

    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception as exc:
        raise VerificationError(
            code="signature_invalid_encoding",
            message="Signature must be valid base64.",
        ) from exc

    payload = _build_signature_payload(manifest)
    try:
        key.verify(
            signature,
            payload,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise VerificationError(
            code="signature_invalid",
            message="Release manifest signature verification failed.",
        ) from exc


def verify_detached_artifact_signature(
    *,
    artifact_bytes: bytes,
    signature_b64: str,
    public_key_pem: str,
    signature_type: str,
) -> None:
    sig_type = signature_type.strip().lower()
    if sig_type not in {"rsa-sha256", "ed25519"}:
        raise VerificationError(
            code="signature_type_unsupported",
            message="Only rsa-sha256 and ed25519 detached artifact signature labels are supported.",
            details={"signature_type": signature_type},
        )
    if not signature_b64.strip():
        raise VerificationError(
            code="signature_missing",
            message="Detached release signature is missing.",
        )
    normalized_public_key_pem = _normalize_public_key_pem(public_key_pem)
    if not normalized_public_key_pem:
        raise VerificationError(
            code="public_key_missing",
            message="Publisher public key is missing.",
        )
    try:
        key = serialization.load_pem_public_key(normalized_public_key_pem.encode("utf-8"))
    except Exception as exc:
        raise VerificationError(
            code="public_key_invalid",
            message="Publisher public key is not a valid PEM RSA public key.",
        ) from exc
    if not isinstance(key, rsa.RSAPublicKey):
        raise VerificationError(
            code="public_key_not_rsa",
            message="Only RSA public keys are supported for addon package verification.",
        )

    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception as exc:
        raise VerificationError(
            code="signature_invalid_encoding",
            message="Signature must be valid base64.",
        ) from exc

    try:
        key.verify(
            signature,
            artifact_bytes,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise VerificationError(
            code="signature_invalid",
            message="Detached artifact signature verification failed.",
        ) from exc


def verify_release_artifact(
    manifest: ReleaseManifest,
    artifact_bytes: bytes,
    public_key_pem: str,
) -> None:
    # Fail closed: verification must pass before any unpack/enable path.
    verify_checksum(artifact_bytes, manifest.checksum)
    verify_rsa_signature(manifest, public_key_pem)


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
