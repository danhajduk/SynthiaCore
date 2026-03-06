#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SEMVER_SUFFIX_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"[A-Za-z][0-9A-Za-z]*$"
)


def _usage() -> None:
    print(
        "Usage:\n"
        "  scripts/validate-catalog-release-versions.py <index.json>\n\n"
        "Checks all release version fields in catalog addons/release/channel entries.\n"
        "Accepted formats:\n"
        "  - semver (example: 1.2.3)\n"
        "  - semver+suffix (example: 1.2.3d)\n",
        file=sys.stderr,
    )


def _normalize_release_entries(raw_channel: Any) -> list[dict[str, Any]]:
    if isinstance(raw_channel, list):
        return [item for item in raw_channel if isinstance(item, dict)]
    if isinstance(raw_channel, dict):
        wrapped = raw_channel.get("releases")
        if isinstance(wrapped, list):
            return [item for item in wrapped if isinstance(item, dict)]
        if "version" in raw_channel:
            return [raw_channel]
    return []


def _collect_releases(item: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    releases: list[tuple[str, dict[str, Any]]] = []
    raw = item.get("releases")
    if isinstance(raw, list):
        for idx, rel in enumerate(raw):
            if isinstance(rel, dict):
                releases.append((f"releases[{idx}]", rel))

    channels = item.get("channels")
    if isinstance(channels, dict):
        for channel_name, channel_value in channels.items():
            for idx, rel in enumerate(_normalize_release_entries(channel_value)):
                releases.append((f"channels.{channel_name}[{idx}]", rel))
    return releases


def _is_valid_release_version(value: str) -> bool:
    return bool(SEMVER_RE.fullmatch(value) or SEMVER_SUFFIX_RE.fullmatch(value))


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] in {"-h", "--help"}:
        _usage()
        return 2 if len(sys.argv) != 2 else 0

    index_path = Path(sys.argv[1]).expanduser().resolve()
    if not index_path.exists() or not index_path.is_file():
        print(f"error: index_not_found: {index_path}", file=sys.stderr)
        return 2

    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"error: invalid_json: {exc}", file=sys.stderr)
        return 2

    addons: list[dict[str, Any]] = []
    if isinstance(payload, dict) and isinstance(payload.get("addons"), list):
        addons = [item for item in payload["addons"] if isinstance(item, dict)]
    elif isinstance(payload, list):
        addons = [item for item in payload if isinstance(item, dict)]
    else:
        print("error: invalid_catalog_shape: expected object with addons[] or top-level array", file=sys.stderr)
        return 2

    errors: list[str] = []
    for addon_index, addon in enumerate(addons):
        addon_id = str(addon.get("id") or addon.get("addon_id") or f"addon[{addon_index}]")
        for release_path, release in _collect_releases(addon):
            version = str(release.get("version") or "").strip()
            if not version:
                errors.append(f"{addon_id} {release_path}: missing version")
                continue
            if not _is_valid_release_version(version):
                errors.append(
                    f"{addon_id} {release_path}: invalid version '{version}' "
                    "(expected semver or semver+suffix like 1.2.3 / 1.2.3d)"
                )

    if errors:
        print("error: catalog_release_version_validation_failed", file=sys.stderr)
        for line in errors:
            print(f" - {line}", file=sys.stderr)
        return 1

    print(f"ok: validated release versions for {len(addons)} addon entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
