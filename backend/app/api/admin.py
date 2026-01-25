from __future__ import annotations

import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException

router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parents[3]  # backend/app/api/admin.py -> repo root
UPDATE_SCRIPT = REPO_ROOT / "scripts" / "bootstrap.sh"
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

    if not UPDATE_SCRIPT.exists():
        raise HTTPException(status_code=500, detail=f"Missing script: {UPDATE_SCRIPT}")

    env = os.environ.copy()
    # run bootstrap in update mode against the *current* install dir
    install_dir = str(REPO_ROOT)
    cmd = ["bash", str(UPDATE_SCRIPT), "--dir", install_dir, "--update"]

    # background run (request will return immediately)
    with open(LOG_FILE, "ab", buffering=0) as f:
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    return {"started": True, "pid": proc.pid, "log": str(LOG_FILE)}

@router.get("/admin/reload/status")
def admin_reload_status(x_admin_token: str | None = Header(default=None)):
    require_admin_token(x_admin_token)

    if not LOG_FILE.exists():
        return {"exists": False, "tail": ""}

    lines = LOG_FILE.read_text(errors="ignore").splitlines()
    tail = "\n".join(lines[-200:])
    return {"exists": True, "tail": tail}
