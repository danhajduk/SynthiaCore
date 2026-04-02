from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class TaskExecutionResolutionRequest(BaseModel):
    node_id: str = Field(..., min_length=1)
    task_family: str = Field(..., min_length=1)
    type: str | None = None
    task_context: dict[str, Any] = Field(default_factory=dict)
    preferred_provider: str | None = None
    preferred_model: str | None = None

    @field_validator("node_id", "task_family", "type", "preferred_provider", "preferred_model")
    @classmethod
    def _clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator("task_context", mode="before")
    @classmethod
    def _normalize_context(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("task_context_must_be_object")
        return dict(value)

    @model_validator(mode="after")
    def _merge_type_into_context(self) -> "TaskExecutionResolutionRequest":
        request_type = str(self.type or "").strip().lower()
        context_type = str(self.task_context.get("type") or "").strip().lower()
        if request_type and context_type and request_type != context_type:
            raise ValueError("task_type_conflict")
        if request_type and not context_type:
            self.task_context["type"] = request_type
        elif context_type:
            self.task_context["type"] = context_type
            self.type = context_type
        return self

    @model_validator(mode="after")
    def _validate_task_family_canonicality(self) -> "TaskExecutionResolutionRequest":
        task_family = str(self.task_family or "").strip().lower()
        preferred_provider = str(self.preferred_provider or "").strip().lower()
        content_type = str(self.task_context.get("content_type") or "").strip().lower()
        request_type = str(self.type or "").strip().lower()
        if preferred_provider and task_family.endswith(f".{preferred_provider}"):
            raise ValueError("task_family_provider_suffix_not_allowed")
        if content_type and task_family.endswith(f".{content_type}"):
            raise ValueError("task_family_context_suffix_not_allowed")
        if request_type and task_family.endswith(f".{request_type}"):
            raise ValueError("task_family_type_suffix_not_allowed")
        return self


class NodeEffectiveBudgetView(BaseModel):
    status: str
    budget_node_id: str | None = None
    enforcement_mode: str | None = None
    grant_id: str | None = None
    service: str | None = None
    provider: str | None = None
    task_family: str | None = None
    model_id: str | None = None
    grant_scope_kind: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    limits: dict[str, Any] = Field(default_factory=dict)
    consumed: dict[str, Any] = Field(default_factory=dict)
    remaining: dict[str, Any] = Field(default_factory=dict)
    admissible: bool = False
    reason: str | None = None


class TaskExecutionResolutionCandidate(BaseModel):
    service_id: str
    provider_node_id: str | None = None
    provider_api_base_url: str | None = None
    service_type: str | None = None
    provider: str | None = None
    models_allowed: list[str] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=list)
    auth_mode: str = "service_token"
    grant_id: str | None = None
    resolution_mode: str = "catalog_governance_budget"
    health_status: str | None = None
    declared_capacity: dict[str, Any] = Field(default_factory=dict)
    budget_view: NodeEffectiveBudgetView | None = None


class TaskExecutionResolutionResponse(BaseModel):
    node_id: str
    task_family: str
    task_context: dict[str, Any] = Field(default_factory=dict)
    selected_service_id: str | None = None
    candidates: list[TaskExecutionResolutionCandidate] = Field(default_factory=list)


class NodeServiceAuthorizeRequest(TaskExecutionResolutionRequest):
    service_id: str | None = None
    provider: str | None = None
    model_id: str | None = None

    @field_validator("service_id", "provider", "model_id")
    @classmethod
    def _clean_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None
