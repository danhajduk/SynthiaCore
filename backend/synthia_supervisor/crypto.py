# synthia_supervisor/crypto.py
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class CryptoError(RuntimeError):
    pass


def _sha256_hex_and_bytes(path: Path) -> Tuple[str, bytes]:
    data = path.read_bytes()
    digest_bytes = hashlib.sha256(data).digest()
    digest_hex = digest_bytes.hex()
    return digest_hex, digest_bytes


def _default_publishers_registry_path() -> Path:
    install_root = Path(__file__).resolve().parents[2]
    return install_root / "runtime" / "store" / "cache" / "official" / "publishers.json"


def _load_publishers_registry() -> dict:
    """
    Loads publishers.json.
    Default path: $SYNTHIA_CATALOG_PUBLISHERS or <install_root>/runtime/store/cache/official/publishers.json
    """
    p = os.environ.get("SYNTHIA_CATALOG_PUBLISHERS")
    if p:
        path = Path(p).expanduser()
    else:
        path = _default_publishers_registry_path()

    if not path.exists():
        raise CryptoError(
            f"publishers.json not found at {path}. "
            f"Set SYNTHIA_CATALOG_PUBLISHERS to the correct path."
        )

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise CryptoError(f"Failed to parse publishers.json at {path}: {e}") from e


def _find_public_key(publishers_doc: dict, publisher_key_id: str) -> str:
    """
    Finds the public key string for a given key_id.
    Expected structure per your catalog spec:
      publishers: [{ keys: [{ key_id, algorithm, public_key, status, ... }] }]
    """
    pubs = publishers_doc.get("publishers", [])
    for pub in pubs:
        for k in pub.get("keys", []):
            if k.get("key_id") == publisher_key_id:
                if k.get("status") == "revoked":
                    raise CryptoError(f"Publisher key is revoked: {publisher_key_id}")
                alg = str(k.get("algorithm") or "").strip().lower()
                if alg not in {"ed25519", "rsa-sha256", "rsa"}:
                    raise CryptoError(f"Unsupported algorithm for {publisher_key_id}: {alg}")
                pk = k.get("public_key")
                if not pk:
                    raise CryptoError(f"Missing public_key for {publisher_key_id}")
                return pk
    raise CryptoError(f"publisher_key_id not found in publishers.json: {publisher_key_id}")


def _decode_public_key(pubkey_str: str) -> bytes:
    """
    Accepts:
      - base64 (preferred)
      - hex
    Returns raw 32-byte ed25519 public key.
    """
    s = pubkey_str.strip()

    # try base64 first
    try:
        b = base64.b64decode(s, validate=True)
        if len(b) == 32:
            return b
    except Exception:
        pass

    # try hex
    try:
        b = bytes.fromhex(s)
        if len(b) == 32:
            return b
    except Exception:
        pass

    raise CryptoError("Invalid ed25519 public key encoding (expected base64 or hex of 32 bytes).")


def _normalize_key_text(public_key: str) -> str:
    text = str(public_key or "").strip()
    if not text:
        return ""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    if "\\n" in text or "\\r" in text:
        text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    return text


def _decode_rsa_public_key(pubkey_str: str) -> rsa.RSAPublicKey:
    text = _normalize_key_text(pubkey_str)
    if not text:
        raise CryptoError("Missing RSA public key.")
    try:
        key = serialization.load_pem_public_key(text.encode("utf-8"))
        if isinstance(key, rsa.RSAPublicKey):
            return key
    except Exception:
        pass
    for candidate in (text,):
        try:
            der = base64.b64decode(candidate, validate=True)
            key = serialization.load_der_public_key(der)
            if isinstance(key, rsa.RSAPublicKey):
                return key
        except Exception:
            pass
    raise CryptoError("Invalid RSA public key encoding (expected PEM or DER/SPKI base64).")


def verify_release_option_a(
    artifact_path: Path,
    expected_sha256_hex: str,
    signature_b64: str,
    publisher_key_id: str,
    signature_type: str = "ed25519",
) -> None:
    """
    Release verification:
      - sha256_hex must match SHA256(artifact_bytes)
      - ed25519: signature verifies over SHA256(artifact_bytes) digest BYTES (Option A)
      - rsa-sha256: detached signature verifies over artifact bytes with PKCS1v15+SHA256
    """
    if not artifact_path.exists():
        raise CryptoError(f"Artifact not found: {artifact_path}")

    expected = expected_sha256_hex.lower().strip()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise CryptoError("expected_sha256_hex must be 64 lowercase hex chars")

    artifact_bytes = artifact_path.read_bytes()
    digest_bytes = hashlib.sha256(artifact_bytes).digest()
    actual_hex = digest_bytes.hex()
    if actual_hex != expected:
        raise CryptoError(f"SHA256 mismatch: expected={expected} actual={actual_hex}")

    # Load publishers.json and resolve public key
    publishers_doc = _load_publishers_registry()
    pubkey_str = _find_public_key(publishers_doc, publisher_key_id)

    # Decode signature
    try:
        sig = base64.b64decode(signature_b64.strip(), validate=True)
    except Exception as e:
        raise CryptoError(f"Invalid signature base64: {e}") from e

    sig_type = signature_type.strip().lower()
    if sig_type not in {"ed25519", "rsa-sha256"}:
        raise CryptoError(
            f"Unsupported signature type: {signature_type}. Supported: ed25519, rsa-sha256."
        )

    if sig_type == "ed25519":
        try:
            pubkey_raw = _decode_public_key(pubkey_str)
            Ed25519PublicKey.from_public_bytes(pubkey_raw).verify(sig, digest_bytes)
            return
        except InvalidSignature as e:
            raise CryptoError("Signature verification failed (ed25519 / Option A).") from e
        except CryptoError:
            if len(sig) == 64:
                raise

    # Legacy compatibility: some catalogs label rsa-sha256 payloads as ed25519.
    rsa_public_key = _decode_rsa_public_key(pubkey_str)
    try:
        rsa_public_key.verify(sig, artifact_bytes, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as e:
        raise CryptoError("Signature verification failed (rsa-sha256 detached).") from e
