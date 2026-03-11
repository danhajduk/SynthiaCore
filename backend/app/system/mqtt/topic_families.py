from __future__ import annotations

from typing import Literal


TopicFamily = Literal[
    "bootstrap",
    "runtime",
    "core",
    "system",
    "supervisor",
    "scheduler",
    "policy",
    "telemetry",
    "events",
    "remote",
    "bridges",
    "import",
    "services",
    "addons",
    "nodes",
    "synthia_other",
    "external",
    "invalid",
]

BOOTSTRAP_TOPIC = "synthia/bootstrap/core"
PLATFORM_RESERVED_PREFIXES: tuple[str, ...] = (
    "synthia/bootstrap/",
    "synthia/runtime/",
    "synthia/system/",
    "synthia/core/",
    "synthia/supervisor/",
    "synthia/scheduler/",
    "synthia/policy/",
    "synthia/telemetry/",
    "synthia/events/",
    "synthia/remote/",
    "synthia/bridges/",
    "synthia/import/",
)
CANONICAL_RESERVED_PREFIXES: tuple[str, ...] = (
    "synthia/#",
    "$SYS/#",
    "synthia/bootstrap/#",
    "synthia/runtime/#",
    "synthia/system/#",
    "synthia/core/#",
    "synthia/supervisor/#",
    "synthia/scheduler/#",
    "synthia/policy/#",
    "synthia/telemetry/#",
    "synthia/events/#",
    "synthia/remote/#",
    "synthia/bridges/#",
    "synthia/import/#",
)
TOP_LEVEL_RESERVED_FAMILIES: tuple[str, ...] = (
    "bootstrap",
    "runtime",
    "core",
    "system",
    "supervisor",
    "scheduler",
    "policy",
    "telemetry",
    "events",
    "remote",
    "bridges",
    "import",
    "services",
    "addons",
    "nodes",
)

# TODO(phase1-topic): Additional planned families/subtrees are documented in docs/mqtt-topic-tree.md
# (for example synthia/nodes/<node_id>/... and synthia/core/status|health|events/...),
# but not all are implemented in runtime behavior yet.


def normalize_topic(raw: str) -> str:
    return str(raw or "").strip()


def topic_parts(topic: str) -> list[str]:
    clean = normalize_topic(topic)
    if not clean:
        return []
    return [part for part in clean.split("/") if part != ""]


def topic_family(topic: str) -> TopicFamily:
    parts = topic_parts(topic)
    if not parts:
        return "invalid"
    if parts[0] != "synthia":
        return "external"
    if len(parts) < 2:
        return "synthia_other"
    family = parts[1]
    if family in {
        "bootstrap",
        "runtime",
        "core",
        "system",
        "supervisor",
        "scheduler",
        "policy",
        "telemetry",
        "events",
        "remote",
        "bridges",
        "import",
        "services",
        "addons",
        "nodes",
    }:
        return family  # type: ignore[return-value]
    return "synthia_other"


def is_synthia_topic(topic: str) -> bool:
    return topic_family(topic) not in {"external", "invalid"}


def is_bootstrap_topic(topic: str) -> bool:
    return normalize_topic(topic) == BOOTSTRAP_TOPIC


def is_platform_reserved_topic(topic: str) -> bool:
    clean = normalize_topic(topic)
    if not clean:
        return False
    return any(clean.startswith(prefix) for prefix in PLATFORM_RESERVED_PREFIXES)


def is_reserved_family_topic(topic: str) -> bool:
    family = topic_family(topic)
    return family in TOP_LEVEL_RESERVED_FAMILIES


def is_addon_scoped_topic(topic: str, addon_id: str | None = None) -> bool:
    parts = topic_parts(topic)
    if len(parts) < 4 or parts[0] != "synthia" or parts[1] != "addons":
        return False
    if addon_id is None:
        return True
    return parts[2] == addon_id


def is_node_scoped_topic(topic: str, node_id: str | None = None) -> bool:
    parts = topic_parts(topic)
    if len(parts) < 4 or parts[0] != "synthia" or parts[1] != "nodes":
        return False
    if node_id is None:
        return True
    return parts[2] == node_id


def is_generic_non_reserved_topic(topic: str) -> bool:
    clean = normalize_topic(topic)
    if not clean:
        return False
    if not is_synthia_topic(clean):
        return True
    return not is_reserved_family_topic(clean)


def is_policy_topic_path(topic: str) -> bool:
    parts = topic_parts(topic)
    if len(parts) != 4:
        return False
    if parts[0] != "synthia" or parts[1] != "policy":
        return False
    if parts[2] not in {"grants", "revocations"}:
        return False
    return bool(parts[3].strip())


def canonical_reserved_prefixes() -> list[str]:
    return sorted({str(item).strip() for item in CANONICAL_RESERVED_PREFIXES if str(item).strip()})
