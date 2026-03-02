from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_desired_state(
    *,
    addon_id: str,
    channel: str,
    pinned_version: str | None,
    artifact_url: str,
    sha256: str,
    publisher_key_id: str,
    signature_value: str,
    runtime_project_name: str,
    runtime_network: str,
    runtime_ports: list[dict[str, Any]] | None = None,
    config_env: dict[str, str] | None = None,
    desired_state: str = "running",
) -> dict[str, Any]:
    return {
        "ssap_version": "1.0",
        "addon_id": addon_id,
        "mode": "standalone_service",
        "desired_state": desired_state,
        "channel": channel,
        "pinned_version": pinned_version,
        "install_source": {
            "type": "catalog",
            "release": {
                "artifact_url": artifact_url,
                "sha256": sha256,
                "publisher_key_id": publisher_key_id,
                "signature": {
                    "type": "ed25519",
                    "value": signature_value,
                },
            },
        },
        "runtime": {
            "orchestrator": "docker_compose",
            "project_name": runtime_project_name,
            "network": runtime_network,
            "ports": list(runtime_ports or []),
        },
        "config": {
            "env": dict(config_env or {}),
        },
    }


def write_desired_state_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)
