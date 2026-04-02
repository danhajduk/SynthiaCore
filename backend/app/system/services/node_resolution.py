from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.nodes.models_resolution import (
    NodeEffectiveBudgetView,
    TaskExecutionResolutionCandidate,
    TaskExecutionResolutionRequest,
    TaskExecutionResolutionResponse,
)


def _clean_text(value: Any, *, lower: bool = False) -> str:
    cleaned = str(value or "").strip()
    return cleaned.lower() if lower else cleaned


def _normalize_url_for_match(value: Any) -> str:
    raw = _clean_text(value)
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.rstrip("/").lower()
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


class NodeServiceResolutionService:
    def __init__(self, catalog_store, *, node_registrations_store=None, model_routing_registry_service=None) -> None:
        self._catalog_store = catalog_store
        self._node_registrations_store = node_registrations_store
        self._model_routing_registry_service = model_routing_registry_service

    def _resolve_provider_node_id(
        self,
        *,
        service_item: dict[str, Any],
        provider: str,
        preferred_model: str,
        allowed_models: list[str],
    ) -> str | None:
        explicit_node_id = _clean_text(
            service_item.get("node_id")
            or ((service_item.get("addon_registry") or {}).get("node_id") if isinstance(service_item.get("addon_registry"), dict) else None)
            or ((service_item.get("declared_capacity") or {}).get("node_id") if isinstance(service_item.get("declared_capacity"), dict) else None)
            or ((service_item.get("service_capacity") or {}).get("node_id") if isinstance(service_item.get("service_capacity"), dict) else None)
        )
        if explicit_node_id:
            return explicit_node_id

        endpoint_candidates = {
            _normalize_url_for_match(service_item.get("endpoint")),
            _normalize_url_for_match(service_item.get("base_url")),
        }
        endpoint_candidates = {item for item in endpoint_candidates if item}

        if self._model_routing_registry_service is not None and provider:
            model_candidates = [preferred_model] if preferred_model else []
            model_candidates.extend([item for item in allowed_models if item and item not in model_candidates])
            registry_matches: list[str] = []
            for model_id in model_candidates:
                for item in self._model_routing_registry_service.list(provider=provider):
                    if not bool(getattr(item, "node_available", True)):
                        continue
                    normalized_model_id = _clean_text(getattr(item, "normalized_model_id", ""), lower=True)
                    raw_model_id = _clean_text(getattr(item, "model_id", ""), lower=True)
                    if model_id and model_id not in {normalized_model_id, raw_model_id}:
                        continue
                    registry_matches.append(_clean_text(getattr(item, "node_id", "")))
            unique_registry_matches = sorted({item for item in registry_matches if item})
            if len(unique_registry_matches) == 1:
                return unique_registry_matches[0]

            if endpoint_candidates and self._node_registrations_store is not None:
                for registration in self._node_registrations_store.list():
                    node_api_base = _normalize_url_for_match(getattr(registration, "api_base_url", None))
                    requested_api_base = _normalize_url_for_match(getattr(registration, "requested_api_base_url", None))
                    if node_api_base in endpoint_candidates or requested_api_base in endpoint_candidates:
                        if registration.node_id in unique_registry_matches:
                            return registration.node_id

            if not model_candidates:
                provider_nodes = sorted(
                    {
                        _clean_text(getattr(item, "node_id", ""))
                        for item in self._model_routing_registry_service.list(provider=provider)
                        if bool(getattr(item, "node_available", True))
                    }
                )
                provider_nodes = [item for item in provider_nodes if item]
                if len(provider_nodes) == 1:
                    return provider_nodes[0]

        if endpoint_candidates and self._node_registrations_store is not None:
            for registration in self._node_registrations_store.list():
                node_api_base = _normalize_url_for_match(getattr(registration, "api_base_url", None))
                requested_api_base = _normalize_url_for_match(getattr(registration, "requested_api_base_url", None))
                if node_api_base in endpoint_candidates or requested_api_base in endpoint_candidates:
                    return registration.node_id
        return None

    def _provider_models_for_registration(self, registration, provider: str) -> list[str]:
        provider_key = _clean_text(provider, lower=True)
        if not provider_key:
            return []
        models: list[str] = []
        for item in list(getattr(registration, "provider_intelligence", []) or []):
            if not isinstance(item, dict):
                continue
            if _clean_text(item.get("provider"), lower=True) != provider_key:
                continue
            for model in list(item.get("available_models") or []):
                if not isinstance(model, dict):
                    continue
                model_id = _clean_text(model.get("normalized_model_id") or model.get("model_id"), lower=True)
                if model_id and model_id not in models:
                    models.append(model_id)
        if models:
            return models
        if self._model_routing_registry_service is None:
            return []
        registry_models = []
        for item in self._model_routing_registry_service.list(node_id=registration.node_id, provider=provider_key):
            model_id = _clean_text(getattr(item, "normalized_model_id", "") or getattr(item, "model_id", ""), lower=True)
            if model_id and model_id not in registry_models and bool(getattr(item, "node_available", True)):
                registry_models.append(model_id)
        return registry_models

    def _provider_api_base_url(self, provider_node_id: str | None, service_item: dict[str, Any]) -> str | None:
        endpoint = _clean_text(service_item.get("endpoint"))
        if endpoint:
            return endpoint
        base_url = _clean_text(service_item.get("base_url"))
        if base_url:
            return base_url
        node_key = _clean_text(provider_node_id)
        if node_key and self._node_registrations_store is not None:
            registration = self._node_registrations_store.get(node_key)
            if registration is not None:
                api_base_url = _clean_text(getattr(registration, "api_base_url", None))
                if api_base_url:
                    return api_base_url
                requested_api_base_url = _clean_text(getattr(registration, "requested_api_base_url", None))
                if requested_api_base_url:
                    return requested_api_base_url
        return base_url or None

    def _declared_node_candidates(self, *, task_family: str) -> list[dict[str, Any]]:
        if self._node_registrations_store is None:
            return []
        service_capacity_by_node: dict[str, dict[str, Any]] = {}
        if self._model_routing_registry_service is not None:
            for item in self._model_routing_registry_service.list_grouped_by_node():
                if not isinstance(item, dict):
                    continue
                node_id = _clean_text(item.get("node_id"))
                if not node_id:
                    continue
                service_capacity_by_node[node_id] = (
                    dict(item.get("service_capacity") or {}) if isinstance(item.get("service_capacity"), dict) else {}
                )

        out: list[dict[str, Any]] = []
        for registration in self._node_registrations_store.list():
            if _clean_text(getattr(registration, "trust_status", ""), lower=True) != "trusted":
                continue
            capabilities = [
                _clean_text(item, lower=True)
                for item in list(getattr(registration, "declared_capabilities", []) or [])
                if _clean_text(item, lower=True)
            ]
            if task_family not in capabilities:
                continue
            providers = [
                _clean_text(item, lower=True)
                for item in list(getattr(registration, "enabled_providers", []) or [])
                if _clean_text(item, lower=True)
            ]
            if not providers:
                providers = [""]
            for provider in providers:
                out.append(
                    {
                        "service_id": f"node-service:{registration.node_id}:{provider or 'default'}",
                        "service_type": "node-runtime",
                        "service": "node-runtime",
                        "node_id": registration.node_id,
                        "endpoint": getattr(registration, "api_base_url", None),
                        "base_url": getattr(registration, "api_base_url", None),
                        "health": "healthy",
                        "health_status": "healthy",
                        "capabilities": capabilities,
                        "provider": provider or None,
                        "models": self._provider_models_for_registration(registration, provider),
                        "declared_capacity": service_capacity_by_node.get(registration.node_id, {}),
                        "auth_mode": "service_token",
                        "auth_modes": ["service_token"],
                        "required_scopes": [f"service.execute:{task_family}"],
                        "addon_registry": {
                            "node_id": registration.node_id,
                            "node_name": getattr(registration, "node_name", None),
                            "node_type": getattr(registration, "node_type", None),
                        },
                    }
                )
        return out

    async def resolve_for_node(
        self,
        *,
        request: TaskExecutionResolutionRequest,
        governance_bundle: dict[str, Any],
        budget_service,
    ) -> TaskExecutionResolutionResponse:
        task_family = _clean_text(request.task_family, lower=True)
        preferred_provider = _clean_text(request.preferred_provider, lower=True)
        preferred_model = _clean_text(request.preferred_model, lower=True)
        routing = (
            governance_bundle.get("routing_policy_constraints")
            if isinstance(governance_bundle.get("routing_policy_constraints"), dict)
            else {}
        )
        allowed_task_families = {
            _clean_text(item, lower=True)
            for item in list(routing.get("allowed_task_families") or [])
            if _clean_text(item, lower=True)
        }
        if allowed_task_families and task_family not in allowed_task_families:
            return TaskExecutionResolutionResponse(
                node_id=request.node_id,
                task_family=task_family,
                task_context=dict(request.task_context or {}),
                selected_service_id=None,
                candidates=[],
            )

        catalogs = await self._catalog_store.all_catalogs()
        catalog_sources: list[dict[str, Any]] = []
        seen_catalog_service_ids: set[str] = set()
        for service_key in sorted(catalogs.keys()):
            item = catalogs.get(service_key)
            if not isinstance(item, dict):
                continue
            service_id = _clean_text(item.get("service_id") or item.get("service") or service_key)
            if not service_id or service_id in seen_catalog_service_ids:
                continue
            seen_catalog_service_ids.add(service_id)
            catalog_sources.append(item)

        def _build_candidates(candidate_sources: list[dict[str, Any]]) -> list[TaskExecutionResolutionCandidate]:
            candidates: list[TaskExecutionResolutionCandidate] = []
            for item in candidate_sources:
                service_key = _clean_text(item.get("service_id") or item.get("service"))
                capabilities = [
                    _clean_text(capability, lower=True)
                    for capability in list(item.get("capabilities") or [])
                    if _clean_text(capability, lower=True)
                ]
                if task_family not in capabilities:
                    continue
                health_status = _clean_text(item.get("health_status") or item.get("health"), lower=True) or "unknown"
                if health_status not in {"ok", "healthy", "unknown"}:
                    continue
                provider = _clean_text(item.get("provider"), lower=True)
                if preferred_provider and provider and provider != preferred_provider:
                    continue

                catalog_models = [
                    _clean_text(model.get("model_id") if isinstance(model, dict) else model, lower=True)
                    for model in list(item.get("models") or [])
                    if _clean_text(model.get("model_id") if isinstance(model, dict) else model, lower=True)
                ]
                allowed_models = catalog_models
                if preferred_model:
                    if allowed_models:
                        allowed_models = [model for model in allowed_models if model == preferred_model]
                    elif preferred_model:
                        allowed_models = [preferred_model]
                if preferred_model and not allowed_models:
                    continue

                provider_node_id = self._resolve_provider_node_id(
                    service_item=item,
                    provider=provider,
                    preferred_model=preferred_model,
                    allowed_models=allowed_models,
                )
                budget_view_payload = budget_service.effective_budget_view(
                    node_id=provider_node_id or request.node_id,
                    task_family=task_family,
                    provider=provider or None,
                    model_id=preferred_model or None,
                )
                budget_view = NodeEffectiveBudgetView.model_validate(budget_view_payload)
                if budget_view.status in {"no_matching_grant", "not_configured", "revoked", "expired"}:
                    continue

                auth_modes = [str(v).strip() for v in list(item.get("auth_modes") or []) if str(v).strip()]
                auth_mode = _clean_text(item.get("auth_mode")) or (auth_modes[0] if auth_modes else "service_token")
                required_scopes = [str(v).strip() for v in list(item.get("required_scopes") or []) if str(v).strip()]
                if not required_scopes:
                    required_scopes = [f"service.execute:{task_family}"]

                declared_capacity = item.get("declared_capacity")
                if not isinstance(declared_capacity, dict):
                    declared_capacity = item.get("service_capacity") if isinstance(item.get("service_capacity"), dict) else {}

                candidates.append(
                    TaskExecutionResolutionCandidate(
                        service_id=_clean_text(item.get("service_id") or item.get("service") or service_key),
                        provider_node_id=provider_node_id or None,
                        provider_api_base_url=self._provider_api_base_url(provider_node_id, item),
                        service_type=_clean_text(item.get("service_type") or item.get("service")),
                        provider=provider or None,
                        models_allowed=allowed_models,
                        required_scopes=required_scopes,
                        auth_mode=auth_mode or "service_token",
                        grant_id=budget_view.grant_id,
                        resolution_mode="catalog_governance_budget",
                        health_status=health_status,
                        declared_capacity=dict(declared_capacity or {}),
                        budget_view=budget_view,
                    )
                )
            return candidates

        candidates = _build_candidates(catalog_sources)
        if not candidates:
            declared_sources: list[dict[str, Any]] = []
            seen_declared_service_ids = set(seen_catalog_service_ids)
            for item in self._declared_node_candidates(task_family=task_family):
                service_id = _clean_text(item.get("service_id"))
                if not service_id or service_id in seen_declared_service_ids:
                    continue
                seen_declared_service_ids.add(service_id)
                declared_sources.append(item)
            candidates = _build_candidates(declared_sources)

        candidates.sort(
            key=lambda item: (
                0 if item.provider and item.provider == preferred_provider else 1,
                0 if item.budget_view and item.budget_view.admissible else 1,
                0 if str(item.health_status or "").lower() in {"ok", "healthy"} else 1,
                str(item.service_id or ""),
            )
        )
        selected_service_id = candidates[0].service_id if candidates else None
        return TaskExecutionResolutionResponse(
            node_id=request.node_id,
            task_family=task_family,
            task_context=dict(request.task_context or {}),
            selected_service_id=selected_service_id,
            candidates=candidates,
        )
