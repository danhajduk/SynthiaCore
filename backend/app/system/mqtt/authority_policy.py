from __future__ import annotations

from typing import Iterable, Literal


RESERVED_PLATFORM_PREFIXES: tuple[str, ...] = (
    "synthia/system/",
    "synthia/core/",
    "synthia/supervisor/",
    "synthia/scheduler/",
    "synthia/policy/",
    "synthia/telemetry/",
)
DEFAULT_BOOTSTRAP_TOPIC = "synthia/bootstrap/core"

MqttAuthorityPrincipalType = Literal["synthia_addon", "synthia_node", "generic_user", "anonymous"]


def _normalize_topic(raw: str) -> str:
    return str(raw or "").strip()


def _matches_prefix(topic: str, prefix: str) -> bool:
    return topic.startswith(prefix)


def is_reserved_platform_topic(topic: str, reserved_prefixes: Iterable[str] | None = None) -> bool:
    clean = _normalize_topic(topic)
    if not clean:
        return False
    prefixes = tuple(reserved_prefixes or RESERVED_PLATFORM_PREFIXES)
    return any(_matches_prefix(clean, prefix) for prefix in prefixes)


def _normalize_approved_reserved(raw: Iterable[str] | None) -> set[str]:
    if raw is None:
        return set()
    return {_normalize_topic(topic) for topic in raw if _normalize_topic(topic)}


def validate_authority_topic_access(
    *,
    principal_type: MqttAuthorityPrincipalType,
    publish_topics: Iterable[str],
    subscribe_topics: Iterable[str],
    bootstrap_topic: str = DEFAULT_BOOTSTRAP_TOPIC,
    approved_reserved_topics: Iterable[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    approved_reserved = _normalize_approved_reserved(approved_reserved_topics)
    bootstrap = _normalize_topic(bootstrap_topic) or DEFAULT_BOOTSTRAP_TOPIC

    for raw in publish_topics:
        topic = _normalize_topic(raw)
        if not topic:
            errors.append("publish topic is empty")
            continue
        if principal_type == "anonymous":
            errors.append(f"anonymous publish topic '{topic}' is not allowed")
            continue
        if principal_type == "generic_user" and is_reserved_platform_topic(topic):
            errors.append(f"generic_user publish topic '{topic}' targets reserved platform namespace")
            continue
        if principal_type in {"synthia_addon", "synthia_node"} and is_reserved_platform_topic(topic):
            if topic not in approved_reserved:
                errors.append(f"{principal_type} publish topic '{topic}' requires explicit reserved approval")

    for raw in subscribe_topics:
        topic = _normalize_topic(raw)
        if not topic:
            errors.append("subscribe topic is empty")
            continue
        if principal_type == "anonymous":
            if topic != bootstrap:
                errors.append(
                    f"anonymous subscribe topic '{topic}' is not allowed; only '{bootstrap}' is permitted"
                )
            continue
        if principal_type == "generic_user" and is_reserved_platform_topic(topic):
            errors.append(f"generic_user subscribe topic '{topic}' targets reserved platform namespace")
            continue
        if principal_type in {"synthia_addon", "synthia_node"} and is_reserved_platform_topic(topic):
            if topic not in approved_reserved:
                errors.append(f"{principal_type} subscribe topic '{topic}' requires explicit reserved approval")
    return errors
