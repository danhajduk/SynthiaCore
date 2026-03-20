#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]

SCAN_PATHS = [
    ROOT / "backend" / "app",
    ROOT / "frontend" / "src",
    ROOT / "frontend" / "index.html",
    ROOT / "frontend" / "package.json",
    ROOT / "systemd",
    ROOT / "scripts",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "index.md",
    ROOT / "docs" / "overview.md",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "mqtt",
    ROOT / "docs" / "nodes",
]

SKIP_PATH_PARTS = {
    "backend/var",
    "docs/archive",
    "docs/addons/standalone-archive",
    "docs/migration",
    "docs/reports",
    "docs/standards",
    "docs/temp-ai-node",
}

ALLOW_PATTERNS = [
    re.compile(r'logging\.getLogger\("synthia\.[^"]+"\)'),
    re.compile(r'"synthia\.[^"]+": \{'),
    re.compile(r"\bsynthia-core\b"),
    re.compile(r"\bSYNTHIA_[A-Z0-9_]+\b"),
    re.compile(r"\bsynthia-[a-z0-9_.-]+\b"),
    re.compile(r"\bbackend/synthia_supervisor\b"),
    re.compile(r"Synthia-Addon-Catalog"),
    re.compile(r"\.config/synthia/"),
    re.compile(r"\$HOME/\.config/synthia"),
    re.compile(r"\.config/synthia/"),
    re.compile(r"scripts/synthia\.env"),
    re.compile(r"DEFAULT_LEGACY_INTERNAL_NAMESPACE"),
    re.compile(r"legacy_internal_namespace"),
    re.compile(r"legacy_compatibility_note"),
    re.compile(r"stable technical identifiers still use `synthia`"),
    re.compile(r"synthia core mqtt"),
]

NEEDLES = [
    re.compile(r"\bSynthia\b"),
    re.compile(r"\bsynthia\b"),
]


def should_skip(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return any(part in rel for part in SKIP_PATH_PARTS)


def allowed(line: str) -> bool:
    stripped = line.strip()
    return any(pattern.search(stripped) for pattern in ALLOW_PATTERNS)


def iter_files(base: Path) -> list[Path]:
    if base.is_file():
        return [base]
    return sorted(path for path in base.rglob("*") if path.is_file())


def main() -> int:
    findings: list[str] = []
    for base in SCAN_PATHS:
        for path in iter_files(base):
            if should_skip(path):
                continue
            if path == Path(__file__).resolve():
                continue
            rel = path.relative_to(ROOT).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if not any(pattern.search(line) for pattern in NEEDLES):
                    continue
                if allowed(line):
                    continue
                findings.append(f"{rel}:{lineno}:{line.strip()}")

    if findings:
        print("Active Hexe branding validation failed.")
        for item in findings:
            print(item)
        return 1

    print("Active Hexe branding validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
