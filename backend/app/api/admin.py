from __future__ import annotations

import os
import subprocess
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException

router = APIRouter()

LOG_FILE = Path("/tmp/synthia_update.log")


def require_admin_token(x_admin_token: str | None) -> None:
    expected = os.getenv("SYNTHIA_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=500, detail="SYNTHIA_ADMIN_TOKEN not configured")
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/admin/reload")
def admin_reload(x_admin_token: str | None = Header(default=None)):
    require_admin_token(x_admin_token)

    # Kick the updater oneshot. This survives the backend restarting.
    try:
        subprocess.run(
            ["systemctl", "--user", "start", "synthia-updater.service"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start updater: {e.stderr or e.stdout or str(e)}",
        )

    return {"started": True, "unit": "synthia-updater.service", "log": str(LOG_FILE)}


@router.get("/admin/reload/status")
def admin_reload_status(x_admin_token: str | None = Header(default=None)):
    require_admin_token(x_admin_token)

    if not LOG_FILE.exists():
        return {"exists": False, "tail": ""}

    lines = LOG_FILE.read_text(errors="ignore").splitlines()
    tail = "\n".join(lines[-200:])
    return {"exists": True, "tail": tail}
