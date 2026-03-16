from __future__ import annotations

from typing import Any

CAPABILITY_TAXONOMY_VERSION = "1"


def _clean_items(values: list[object]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _model_items(provider_intelligence: list[dict[str, Any]]) -> list[str]:
    values: list[object] = []
    for provider in provider_intelligence:
        if not isinstance(provider, dict):
            continue
        for model in list(provider.get("available_models") or []):
            if not isinstance(model, dict):
                continue
            values.append(model.get("normalized_model_id") or model.get("model_id"))
    return _clean_items(values)


def capability_activation_summary(
    *,
    capability_status: str | None,
    governance_sync_status: str | None,
    operational_ready: bool,
) -> dict[str, object]:
    capability = str(capability_status or "missing").strip().lower() or "missing"
    governance = str(governance_sync_status or "pending").strip().lower() or "pending"
    declaration_received = capability in {"declared", "accepted"}
    profile_accepted = capability == "accepted"
    governance_issued = governance == "issued"
    if operational_ready:
        stage = "operational"
    elif governance_issued and profile_accepted:
        stage = "governance_issued"
    elif profile_accepted:
        stage = "profile_accepted"
    elif declaration_received:
        stage = "declaration_received"
    else:
        stage = "not_declared"
    return {
        "stage": stage,
        "declaration_received": declaration_received,
        "profile_accepted": profile_accepted,
        "governance_issued": governance_issued,
        "operational": bool(operational_ready),
    }


def capability_taxonomy_payload(
    *,
    declared_task_families: list[object] | None = None,
    enabled_providers: list[object] | None = None,
    provider_intelligence: list[dict[str, Any]] | None = None,
    capability_status: str | None = None,
    governance_sync_status: str | None = None,
    operational_ready: bool = False,
) -> dict[str, object]:
    categories = [
        {
            "category_id": "task_families",
            "label": "Task families",
            "items": _clean_items(list(declared_task_families or [])),
        },
        {
            "category_id": "provider_access",
            "label": "Provider access",
            "items": _clean_items(list(enabled_providers or [])),
        },
        {
            "category_id": "provider_models",
            "label": "Provider models",
            "items": _model_items([dict(item) for item in list(provider_intelligence or []) if isinstance(item, dict)]),
        },
    ]
    for category in categories:
        category["item_count"] = len(category["items"])
    return {
        "version": CAPABILITY_TAXONOMY_VERSION,
        "categories": categories,
        "activation": capability_activation_summary(
            capability_status=capability_status,
            governance_sync_status=governance_sync_status,
            operational_ready=operational_ready,
        ),
    }
