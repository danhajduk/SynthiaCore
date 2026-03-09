from __future__ import annotations

from typing import Iterable

from .authority_policy import validate_authority_topic_access

RESERVED_PLATFORM_NAMESPACES: tuple[str, ...] = (
    "synthia/system/",
    "synthia/core/",
    "synthia/supervisor/",
    "synthia/scheduler/",
    "synthia/policy/",
    "synthia/telemetry/",
)


def _normalize_topic(raw: str) -> str:
    return str(raw or "").strip()


def _is_addon_namespace(topic: str, addon_id: str) -> bool:
    return topic.startswith(f"synthia/addons/{addon_id}/")


def _is_reserved(topic: str) -> bool:
    return any(topic.startswith(prefix) for prefix in RESERVED_PLATFORM_NAMESPACES)


def validate_topic_scopes(
    addon_id: str,
    publish_topics: Iterable[str],
    subscribe_topics: Iterable[str],
    *,
    approved_reserved_topics: Iterable[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    for raw in publish_topics:
        topic = _normalize_topic(raw)
        if not topic:
            errors.append("publish topic is empty")
            continue
        if not topic.startswith("synthia/"):
            errors.append(f"publish topic '{topic}' must start with 'synthia/'")
            continue
        if _is_reserved(topic):
            continue
        if not _is_addon_namespace(topic, addon_id):
            errors.append(f"publish topic '{topic}' must remain under synthia/addons/{addon_id}/...")

    for raw in subscribe_topics:
        topic = _normalize_topic(raw)
        if not topic:
            errors.append("subscribe topic is empty")
            continue
        if not topic.startswith("synthia/"):
            errors.append(f"subscribe topic '{topic}' must start with 'synthia/'")
            continue
        if _is_addon_namespace(topic, addon_id) or _is_reserved(topic):
            continue
        errors.append(f"subscribe topic '{topic}' is outside allowed namespaces")
    policy_errors = validate_authority_topic_access(
        principal_type="synthia_addon",
        publish_topics=publish_topics,
        subscribe_topics=subscribe_topics,
        approved_reserved_topics=approved_reserved_topics,
    )
    errors.extend(policy_errors)
    return sorted(set(errors))
