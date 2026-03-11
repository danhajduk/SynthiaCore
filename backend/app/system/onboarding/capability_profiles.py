from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CAPABILITY_PROFILE_SCHEMA_VERSION = "1"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    # backend/app/system/onboarding/capability_profiles.py -> onboarding(0), system(1), app(2), backend(3), repo(4)
    return Path(__file__).resolve().parents[4]


def _manifest_digest(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class NodeCapabilityProfileRecord:
    profile_id: str
    node_id: str
    declared_task_families: list[str]
    enabled_providers: list[str]
    feature_flags: dict[str, bool]
    acceptance_timestamp: str
    manifest_version: str
    declaration_digest: str
    declaration_raw: dict[str, Any]
    schema_version: str = CAPABILITY_PROFILE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "node_id": self.node_id,
            "declared_task_families": list(self.declared_task_families or []),
            "enabled_providers": list(self.enabled_providers or []),
            "feature_flags": dict(self.feature_flags or {}),
            "acceptance_timestamp": self.acceptance_timestamp,
            "manifest_version": self.manifest_version,
            "declaration_digest": self.declaration_digest,
            "declaration_raw": copy.deepcopy(self.declaration_raw or {}),
        }


class NodeCapabilityProfilesStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (_repo_root() / "data" / "node_capability_profiles.json")
        self._items: dict[str, NodeCapabilityProfileRecord] = {}
        self._order: list[str] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        items = raw.get("items")
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            profile_id = str(item.get("profile_id") or "").strip()
            node_id = str(item.get("node_id") or "").strip()
            accepted_at = str(item.get("acceptance_timestamp") or "").strip()
            manifest_version = str(item.get("manifest_version") or "").strip()
            digest = str(item.get("declaration_digest") or "").strip()
            if not (profile_id and node_id and accepted_at and manifest_version and digest):
                continue
            declared = item.get("declared_task_families") if isinstance(item.get("declared_task_families"), list) else []
            providers = item.get("enabled_providers") if isinstance(item.get("enabled_providers"), list) else []
            features = item.get("feature_flags") if isinstance(item.get("feature_flags"), dict) else {}
            raw_manifest = item.get("declaration_raw") if isinstance(item.get("declaration_raw"), dict) else {}
            record = NodeCapabilityProfileRecord(
                profile_id=profile_id,
                node_id=node_id,
                declared_task_families=[str(v).strip() for v in declared if str(v).strip()],
                enabled_providers=[str(v).strip() for v in providers if str(v).strip()],
                feature_flags={str(k): bool(v) for k, v in features.items()},
                acceptance_timestamp=accepted_at,
                manifest_version=manifest_version,
                declaration_digest=digest,
                declaration_raw=copy.deepcopy(raw_manifest),
                schema_version=str(item.get("schema_version") or CAPABILITY_PROFILE_SCHEMA_VERSION),
            )
            self._items[profile_id] = record
            self._order.append(profile_id)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": CAPABILITY_PROFILE_SCHEMA_VERSION,
            "items": [self._items[pid].to_dict() for pid in self._order if pid in self._items],
        }
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def list(self, *, node_id: str | None = None) -> list[NodeCapabilityProfileRecord]:
        out: list[NodeCapabilityProfileRecord] = []
        filter_node = str(node_id or "").strip()
        for pid in self._order:
            record = self._items.get(pid)
            if record is None:
                continue
            if filter_node and record.node_id != filter_node:
                continue
            out.append(record)
        return out

    def get(self, profile_id: str) -> NodeCapabilityProfileRecord | None:
        return self._items.get(str(profile_id or "").strip())

    def latest_for_node(self, node_id: str) -> NodeCapabilityProfileRecord | None:
        items = self.list(node_id=node_id)
        if not items:
            return None
        return items[-1]

    def create_or_get(
        self,
        *,
        node_id: str,
        manifest: dict[str, Any],
        declared_task_families: list[str],
        enabled_providers: list[str],
        feature_flags: dict[str, bool],
        manifest_version: str,
    ) -> NodeCapabilityProfileRecord:
        node_key = str(node_id or "").strip()
        if not node_key:
            raise ValueError("node_id_required")
        digest = _manifest_digest(manifest)
        latest = self.latest_for_node(node_key)
        if latest is not None and latest.declaration_digest == digest:
            return latest

        next_version = 1
        for item in self.list(node_id=node_key):
            pid = str(item.profile_id or "")
            prefix = f"cap-{node_key}-v"
            if not pid.startswith(prefix):
                continue
            suffix = pid[len(prefix) :]
            try:
                next_version = max(next_version, int(suffix) + 1)
            except Exception:
                continue
        profile_id = f"cap-{node_key}-v{next_version}"
        record = NodeCapabilityProfileRecord(
            profile_id=profile_id,
            node_id=node_key,
            declared_task_families=[str(v).strip() for v in declared_task_families if str(v).strip()],
            enabled_providers=[str(v).strip() for v in enabled_providers if str(v).strip()],
            feature_flags={str(k): bool(v) for k, v in feature_flags.items()},
            acceptance_timestamp=_utcnow_iso(),
            manifest_version=str(manifest_version or "").strip(),
            declaration_digest=digest,
            declaration_raw=copy.deepcopy(manifest),
        )
        self._items[profile_id] = record
        self._order.append(profile_id)
        self._save()
        return record
