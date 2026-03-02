
import hashlib, base64
from pathlib import Path

def verify_release_option_a(artifact_path: Path, expected_sha256: str, signature_b64: str):
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise RuntimeError("SHA256 mismatch")
    # Signature verification stub — integrate ed25519 lib here
    return True
