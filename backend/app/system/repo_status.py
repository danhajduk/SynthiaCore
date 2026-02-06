# backend/app/system/repo_status.py
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from fastapi import APIRouter

router = APIRouter()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _run_git(args: list[str]) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return res.stdout.strip()


def _status_sync() -> dict:
    try:
        _ = _run_git(["rev-parse", "--is-inside-work-tree"])
    except Exception as e:
        return {"ok": False, "error": f"not_a_git_repo: {e}"}

    fetch_error = None
    try:
        _run_git(["fetch", "origin", "main", "--quiet"])
    except Exception as e:
        fetch_error = str(e)

    try:
        local_sha = _run_git(["rev-parse", "HEAD"])
        remote_sha = _run_git(["rev-parse", "origin/main"])
        counts = _run_git(["rev-list", "--left-right", "--count", "HEAD...origin/main"])
        ahead_str, behind_str = counts.split()
        ahead = int(ahead_str)
        behind = int(behind_str)
    except Exception as e:
        return {"ok": False, "error": f"git_error: {e}", "fetch_error": fetch_error}

    status = "up_to_date"
    if behind > 0 and ahead == 0:
        status = "behind"
    elif ahead > 0 and behind == 0:
        status = "ahead"
    elif ahead > 0 and behind > 0:
        status = "diverged"

    return {
        "ok": True,
        "status": status,
        "update_available": behind > 0,
        "ahead": ahead,
        "behind": behind,
        "local_sha": local_sha,
        "remote_sha": remote_sha,
        "fetch_error": fetch_error,
    }


@router.get("/repo/status")
async def repo_status():
    return await asyncio.to_thread(_status_sync)
