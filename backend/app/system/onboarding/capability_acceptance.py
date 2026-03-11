from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .capability_manifest import SUPPORTED_CAPABILITY_DECLARATION_VERSIONS
from .capability_profiles import NodeCapabilityProfileRecord, NodeCapabilityProfilesStore


def _normalized_set(raw: str) -> set[str]:
    return {str(item or "").strip().lower() for item in str(raw or "").split(",") if str(item or "").strip()}


def _allowed_task_families() -> set[str]:
    return _normalized_set(os.getenv("SYNTHIA_NODE_ALLOWED_TASK_FAMILIES", ""))


def _allowed_providers() -> set[str]:
    configured = _normalized_set(os.getenv("SYNTHIA_NODE_ALLOWED_PROVIDERS", ""))
    if configured:
        return configured
    return {"openai", "local-llm", "local-cpu", "anthropic", "google"}


@dataclass
class CapabilityAcceptanceResult:
    accepted: bool
    error_code: str | None = None
    message: str | None = None
    profile: NodeCapabilityProfileRecord | None = None


class NodeCapabilityAcceptanceService:
    def __init__(self, profile_store: NodeCapabilityProfilesStore) -> None:
        self._profiles = profile_store

    def evaluate(self, *, node_id: str, manifest: dict[str, Any]) -> CapabilityAcceptanceResult:
        version = str(manifest.get("manifest_version") or "").strip()
        if version not in SUPPORTED_CAPABILITY_DECLARATION_VERSIONS:
            return CapabilityAcceptanceResult(
                accepted=False,
                error_code="unsupported_capability_version",
                message=f"manifest_version={version or 'missing'}",
            )

        families = [str(v).strip().lower() for v in list(manifest.get("declared_task_families") or []) if str(v).strip()]
        providers_supported = [
            str(v).strip().lower() for v in list(manifest.get("supported_providers") or []) if str(v).strip()
        ]
        providers_enabled = [str(v).strip().lower() for v in list(manifest.get("enabled_providers") or []) if str(v).strip()]

        allowed_families = _allowed_task_families()
        if allowed_families:
            unsupported = sorted(set(families) - allowed_families)
            if unsupported:
                return CapabilityAcceptanceResult(
                    accepted=False,
                    error_code="unsupported_task_family",
                    message=",".join(unsupported),
                )

        allowed_providers = _allowed_providers()
        unsupported_providers = sorted((set(providers_supported) | set(providers_enabled)) - allowed_providers)
        if unsupported_providers:
            return CapabilityAcceptanceResult(
                accepted=False,
                error_code="unsupported_provider_identifier",
                message=",".join(unsupported_providers),
            )

        if any(provider not in providers_supported for provider in providers_enabled):
            return CapabilityAcceptanceResult(
                accepted=False,
                error_code="enabled_provider_not_supported",
                message="enabled providers must be subset of supported providers",
            )

        feature_raw = manifest.get("node_features")
        feature_flags = feature_raw if isinstance(feature_raw, dict) else {}
        normalized_features = {str(k): bool(v) for k, v in feature_flags.items()}

        profile = self._profiles.create_or_get(
            node_id=node_id,
            manifest=manifest,
            declared_task_families=families,
            enabled_providers=providers_enabled,
            feature_flags=normalized_features,
            manifest_version=version,
        )
        return CapabilityAcceptanceResult(accepted=True, profile=profile)

    def list_profiles(self, *, node_id: str | None = None) -> list[NodeCapabilityProfileRecord]:
        return self._profiles.list(node_id=node_id)

    def get_profile(self, profile_id: str) -> NodeCapabilityProfileRecord | None:
        return self._profiles.get(profile_id)

    def latest_profile_for_node(self, node_id: str) -> NodeCapabilityProfileRecord | None:
        return self._profiles.latest_for_node(node_id)
