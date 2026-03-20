from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NODE_BUDGET_SCHEMA_VERSION = "1"
ALLOCATION_KINDS = {"customer", "provider"}
RESERVATION_STATES = {"reserved", "finalized", "released"}
SUPPORTED_PERIODS = {"monthly", "daily", "manual_reset"}
SUPPORTED_RESET_POLICIES = {"calendar", "rolling", "manual"}
SUPPORTED_ENFORCEMENT_MODES = {"hard_stop", "warn"}
SUPPORTED_COMPUTE_UNITS = {"cost_units", "tokens", "requests", "gpu_seconds", "cpu_seconds"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _clean_text(value: Any, *, lower: bool = False) -> str:
    text = str(value or "").strip()
    return text.lower() if lower else text


def _coerce_optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    amount = float(value)
    if amount < 0:
        raise ValueError("budget_value_must_be_non_negative")
    return amount


@dataclass
class NodeBudgetCapabilityRecord:
    node_id: str
    currency: str
    compute_unit: str
    default_period: str
    supports_money_budget: bool
    supports_compute_budget: bool
    supports_customer_allocations: bool
    supports_provider_allocations: bool
    supported_providers: list[str] = field(default_factory=list)
    setup_requirements: list[str] = field(default_factory=list)
    suggested_money_limit: float | None = None
    suggested_compute_limit: float | None = None
    declared_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    schema_version: str = NODE_BUDGET_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "node_id": self.node_id,
            "currency": self.currency,
            "compute_unit": self.compute_unit,
            "default_period": self.default_period,
            "supports_money_budget": self.supports_money_budget,
            "supports_compute_budget": self.supports_compute_budget,
            "supports_customer_allocations": self.supports_customer_allocations,
            "supports_provider_allocations": self.supports_provider_allocations,
            "supported_providers": list(self.supported_providers or []),
            "setup_requirements": list(self.setup_requirements or []),
            "suggested_money_limit": self.suggested_money_limit,
            "suggested_compute_limit": self.suggested_compute_limit,
            "declared_at": self.declared_at,
            "updated_at": self.updated_at,
        }


@dataclass
class NodeBudgetConfigRecord:
    node_id: str
    currency: str
    compute_unit: str
    period: str
    reset_policy: str
    enforcement_mode: str
    overcommit_enabled: bool
    shared_customer_pool: bool
    shared_provider_pool: bool
    node_money_limit: float | None = None
    node_compute_limit: float | None = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    schema_version: str = NODE_BUDGET_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "node_id": self.node_id,
            "currency": self.currency,
            "compute_unit": self.compute_unit,
            "period": self.period,
            "reset_policy": self.reset_policy,
            "enforcement_mode": self.enforcement_mode,
            "overcommit_enabled": self.overcommit_enabled,
            "shared_customer_pool": self.shared_customer_pool,
            "shared_provider_pool": self.shared_provider_pool,
            "node_money_limit": self.node_money_limit,
            "node_compute_limit": self.node_compute_limit,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class NodeBudgetAllocationRecord:
    node_id: str
    kind: str
    subject_id: str
    money_limit: float | None = None
    compute_limit: float | None = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    schema_version: str = NODE_BUDGET_SCHEMA_VERSION

    @property
    def key(self) -> str:
        return f"{self.node_id}:{self.kind}:{self.subject_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "node_id": self.node_id,
            "kind": self.kind,
            "subject_id": self.subject_id,
            "money_limit": self.money_limit,
            "compute_limit": self.compute_limit,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class NodeBudgetReservationRecord:
    reservation_id: str
    job_id: str
    node_id: str
    source: str
    customer_id: str | None = None
    provider_id: str | None = None
    money_reserved: float | None = None
    compute_reserved: float | None = None
    money_actual: float | None = None
    compute_actual: float | None = None
    lease_id: str | None = None
    state: str = "reserved"
    release_reason: str | None = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    finalized_at: str | None = None
    released_at: str | None = None
    schema_version: str = NODE_BUDGET_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "reservation_id": self.reservation_id,
            "job_id": self.job_id,
            "node_id": self.node_id,
            "source": self.source,
            "customer_id": self.customer_id,
            "provider_id": self.provider_id,
            "money_reserved": self.money_reserved,
            "compute_reserved": self.compute_reserved,
            "money_actual": self.money_actual,
            "compute_actual": self.compute_actual,
            "lease_id": self.lease_id,
            "state": self.state,
            "release_reason": self.release_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finalized_at": self.finalized_at,
            "released_at": self.released_at,
        }


class NodeBudgetStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (_repo_root() / "data" / "node_budgets.json")
        self._declarations: dict[str, NodeBudgetCapabilityRecord] = {}
        self._configs: dict[str, NodeBudgetConfigRecord] = {}
        self._allocations: dict[str, NodeBudgetAllocationRecord] = {}
        self._reservations: dict[str, NodeBudgetReservationRecord] = {}
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
        for item in raw.get("declarations") or []:
            if not isinstance(item, dict):
                continue
            node_id = _clean_text(item.get("node_id"))
            if not node_id:
                continue
            self._declarations[node_id] = NodeBudgetCapabilityRecord(
                node_id=node_id,
                currency=_clean_text(item.get("currency")).upper() or "USD",
                compute_unit=_clean_text(item.get("compute_unit"), lower=True) or "cost_units",
                default_period=_clean_text(item.get("default_period"), lower=True) or "monthly",
                supports_money_budget=bool(item.get("supports_money_budget", True)),
                supports_compute_budget=bool(item.get("supports_compute_budget", True)),
                supports_customer_allocations=bool(item.get("supports_customer_allocations", True)),
                supports_provider_allocations=bool(item.get("supports_provider_allocations", False)),
                supported_providers=sorted(
                    {
                        _clean_text(value, lower=True)
                        for value in list(item.get("supported_providers") or [])
                        if _clean_text(value, lower=True)
                    }
                ),
                setup_requirements=sorted(
                    {
                        _clean_text(value, lower=True)
                        for value in list(item.get("setup_requirements") or [])
                        if _clean_text(value, lower=True)
                    }
                ),
                suggested_money_limit=item.get("suggested_money_limit"),
                suggested_compute_limit=item.get("suggested_compute_limit"),
                declared_at=_clean_text(item.get("declared_at")) or _utcnow_iso(),
                updated_at=_clean_text(item.get("updated_at")) or _utcnow_iso(),
                schema_version=_clean_text(item.get("schema_version")) or NODE_BUDGET_SCHEMA_VERSION,
            )
        for item in raw.get("configs") or []:
            if not isinstance(item, dict):
                continue
            node_id = _clean_text(item.get("node_id"))
            if not node_id:
                continue
            self._configs[node_id] = NodeBudgetConfigRecord(
                node_id=node_id,
                currency=_clean_text(item.get("currency")).upper() or "USD",
                compute_unit=_clean_text(item.get("compute_unit"), lower=True) or "cost_units",
                period=_clean_text(item.get("period"), lower=True) or "monthly",
                reset_policy=_clean_text(item.get("reset_policy"), lower=True) or "calendar",
                enforcement_mode=_clean_text(item.get("enforcement_mode"), lower=True) or "hard_stop",
                overcommit_enabled=bool(item.get("overcommit_enabled", False)),
                shared_customer_pool=bool(item.get("shared_customer_pool", False)),
                shared_provider_pool=bool(item.get("shared_provider_pool", False)),
                node_money_limit=item.get("node_money_limit"),
                node_compute_limit=item.get("node_compute_limit"),
                created_at=_clean_text(item.get("created_at")) or _utcnow_iso(),
                updated_at=_clean_text(item.get("updated_at")) or _utcnow_iso(),
                schema_version=_clean_text(item.get("schema_version")) or NODE_BUDGET_SCHEMA_VERSION,
            )
        for item in raw.get("allocations") or []:
            if not isinstance(item, dict):
                continue
            record = NodeBudgetAllocationRecord(
                node_id=_clean_text(item.get("node_id")),
                kind=_clean_text(item.get("kind"), lower=True),
                subject_id=_clean_text(item.get("subject_id"), lower=True),
                money_limit=item.get("money_limit"),
                compute_limit=item.get("compute_limit"),
                created_at=_clean_text(item.get("created_at")) or _utcnow_iso(),
                updated_at=_clean_text(item.get("updated_at")) or _utcnow_iso(),
                schema_version=_clean_text(item.get("schema_version")) or NODE_BUDGET_SCHEMA_VERSION,
            )
            if record.node_id and record.kind in ALLOCATION_KINDS and record.subject_id:
                self._allocations[record.key] = record
        for item in raw.get("reservations") or []:
            if not isinstance(item, dict):
                continue
            reservation_id = _clean_text(item.get("reservation_id"))
            job_id = _clean_text(item.get("job_id"))
            node_id = _clean_text(item.get("node_id"))
            state = _clean_text(item.get("state"), lower=True) or "reserved"
            if not reservation_id or not job_id or not node_id or state not in RESERVATION_STATES:
                continue
            self._reservations[reservation_id] = NodeBudgetReservationRecord(
                reservation_id=reservation_id,
                job_id=job_id,
                node_id=node_id,
                source=_clean_text(item.get("source")) or "scheduler.queue",
                customer_id=_clean_text(item.get("customer_id"), lower=True) or None,
                provider_id=_clean_text(item.get("provider_id"), lower=True) or None,
                money_reserved=item.get("money_reserved"),
                compute_reserved=item.get("compute_reserved"),
                money_actual=item.get("money_actual"),
                compute_actual=item.get("compute_actual"),
                lease_id=_clean_text(item.get("lease_id")) or None,
                state=state,
                release_reason=_clean_text(item.get("release_reason")) or None,
                created_at=_clean_text(item.get("created_at")) or _utcnow_iso(),
                updated_at=_clean_text(item.get("updated_at")) or _utcnow_iso(),
                finalized_at=_clean_text(item.get("finalized_at")) or None,
                released_at=_clean_text(item.get("released_at")) or None,
                schema_version=_clean_text(item.get("schema_version")) or NODE_BUDGET_SCHEMA_VERSION,
            )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": NODE_BUDGET_SCHEMA_VERSION,
            "declarations": [item.to_dict() for item in sorted(self._declarations.values(), key=lambda value: value.node_id)],
            "configs": [item.to_dict() for item in sorted(self._configs.values(), key=lambda value: value.node_id)],
            "allocations": [
                item.to_dict()
                for item in sorted(self._allocations.values(), key=lambda value: (value.node_id, value.kind, value.subject_id))
            ],
            "reservations": [
                item.to_dict()
                for item in sorted(self._reservations.values(), key=lambda value: (value.node_id, value.created_at, value.job_id))
            ],
        }
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def get_declaration(self, node_id: str) -> NodeBudgetCapabilityRecord | None:
        return self._declarations.get(_clean_text(node_id))

    def upsert_declaration(self, record: NodeBudgetCapabilityRecord) -> NodeBudgetCapabilityRecord:
        existing = self._declarations.get(record.node_id)
        if existing is not None:
            record.declared_at = existing.declared_at
        record.updated_at = _utcnow_iso()
        self._declarations[record.node_id] = record
        self._save()
        return record

    def get_config(self, node_id: str) -> NodeBudgetConfigRecord | None:
        return self._configs.get(_clean_text(node_id))

    def upsert_config(self, record: NodeBudgetConfigRecord) -> NodeBudgetConfigRecord:
        existing = self._configs.get(record.node_id)
        if existing is not None:
            record.created_at = existing.created_at
        record.updated_at = _utcnow_iso()
        self._configs[record.node_id] = record
        self._save()
        return record

    def replace_allocations(self, node_id: str, kind: str, allocations: list[NodeBudgetAllocationRecord]) -> list[NodeBudgetAllocationRecord]:
        node_key = _clean_text(node_id)
        kind_key = _clean_text(kind, lower=True)
        self._allocations = {
            key: value for key, value in self._allocations.items() if not (value.node_id == node_key and value.kind == kind_key)
        }
        for record in allocations:
            self._allocations[record.key] = record
        self._save()
        return self.list_allocations(node_key, kind=kind_key)

    def list_allocations(self, node_id: str | None = None, *, kind: str | None = None) -> list[NodeBudgetAllocationRecord]:
        node_key = _clean_text(node_id)
        kind_key = _clean_text(kind, lower=True)
        items = []
        for item in sorted(self._allocations.values(), key=lambda value: (value.node_id, value.kind, value.subject_id)):
            if node_key and item.node_id != node_key:
                continue
            if kind_key and item.kind != kind_key:
                continue
            items.append(item)
        return items

    def get_reservation_by_job(self, job_id: str) -> NodeBudgetReservationRecord | None:
        job_key = _clean_text(job_id)
        if not job_key:
            return None
        for item in self._reservations.values():
            if item.job_id == job_key:
                return item
        return None

    def upsert_reservation(self, record: NodeBudgetReservationRecord) -> NodeBudgetReservationRecord:
        existing = self._reservations.get(record.reservation_id)
        if existing is not None:
            record.created_at = existing.created_at
        record.updated_at = _utcnow_iso()
        self._reservations[record.reservation_id] = record
        self._save()
        return record

    def list_reservations(self, node_id: str | None = None, *, state: str | None = None) -> list[NodeBudgetReservationRecord]:
        node_key = _clean_text(node_id)
        state_key = _clean_text(state, lower=True)
        items = []
        for item in sorted(self._reservations.values(), key=lambda value: (value.node_id, value.created_at, value.job_id)):
            if node_key and item.node_id != node_key:
                continue
            if state_key and item.state != state_key:
                continue
            items.append(item)
        return items

    def list_bundles(self) -> list[dict[str, Any]]:
        node_ids = sorted(
            set(self._declarations.keys())
            | set(self._configs.keys())
            | {item.node_id for item in self._allocations.values()}
            | {item.node_id for item in self._reservations.values()}
        )
        return [self.bundle(node_id) for node_id in node_ids]

    def bundle(self, node_id: str) -> dict[str, Any]:
        declaration = self.get_declaration(node_id)
        config = self.get_config(node_id)
        customers = [item.to_dict() for item in self.list_allocations(node_id, kind="customer")]
        providers = [item.to_dict() for item in self.list_allocations(node_id, kind="provider")]
        setup_status = "not_declared"
        if declaration is not None:
            setup_status = "configured" if config is not None else "needs_configuration"
        return {
            "node_id": _clean_text(node_id),
            "setup_status": setup_status,
            "declaration": declaration.to_dict() if declaration is not None else None,
            "node_budget": config.to_dict() if config is not None else None,
            "customer_allocations": customers,
            "provider_allocations": providers,
        }


class NodeBudgetService:
    def __init__(self, store: NodeBudgetStore) -> None:
        self._store = store

    def declare_budget_capabilities(self, *, node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        node_key = _clean_text(node_id)
        if not node_key:
            raise ValueError("node_id_required")
        compute_unit = _clean_text(payload.get("compute_unit"), lower=True) or "cost_units"
        if compute_unit not in SUPPORTED_COMPUTE_UNITS:
            raise ValueError("unsupported_compute_unit")
        default_period = _clean_text(payload.get("default_period"), lower=True) or "monthly"
        if default_period not in SUPPORTED_PERIODS:
            raise ValueError("unsupported_budget_period")
        declaration = NodeBudgetCapabilityRecord(
            node_id=node_key,
            currency=_clean_text(payload.get("currency")).upper() or "USD",
            compute_unit=compute_unit,
            default_period=default_period,
            supports_money_budget=bool(payload.get("supports_money_budget", True)),
            supports_compute_budget=bool(payload.get("supports_compute_budget", True)),
            supports_customer_allocations=bool(payload.get("supports_customer_allocations", True)),
            supports_provider_allocations=bool(payload.get("supports_provider_allocations", False)),
            supported_providers=sorted(
                {
                    _clean_text(value, lower=True)
                    for value in list(payload.get("supported_providers") or [])
                    if _clean_text(value, lower=True)
                }
            ),
            setup_requirements=sorted(
                {
                    _clean_text(value, lower=True)
                    for value in list(payload.get("setup_requirements") or [])
                    if _clean_text(value, lower=True)
                }
            ),
            suggested_money_limit=_coerce_optional_float(payload.get("suggested_money_limit")),
            suggested_compute_limit=_coerce_optional_float(payload.get("suggested_compute_limit")),
        )
        return self._store.upsert_declaration(declaration).to_dict()

    def configure_node_budget(
        self,
        *,
        node_id: str,
        node_budget: dict[str, Any],
        customer_allocations: list[dict[str, Any]] | None = None,
        provider_allocations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        node_key = _clean_text(node_id)
        if not node_key:
            raise ValueError("node_id_required")
        declaration = self._store.get_declaration(node_key)
        if declaration is None:
            raise ValueError("budget_capabilities_not_declared")

        currency = _clean_text(node_budget.get("currency")).upper() or declaration.currency or "USD"
        compute_unit = _clean_text(node_budget.get("compute_unit"), lower=True) or declaration.compute_unit
        if compute_unit not in SUPPORTED_COMPUTE_UNITS:
            raise ValueError("unsupported_compute_unit")
        period = _clean_text(node_budget.get("period"), lower=True) or declaration.default_period
        if period not in SUPPORTED_PERIODS:
            raise ValueError("unsupported_budget_period")
        reset_policy = _clean_text(node_budget.get("reset_policy"), lower=True) or "calendar"
        if reset_policy not in SUPPORTED_RESET_POLICIES:
            raise ValueError("unsupported_reset_policy")
        enforcement_mode = _clean_text(node_budget.get("enforcement_mode"), lower=True) or "hard_stop"
        if enforcement_mode not in SUPPORTED_ENFORCEMENT_MODES:
            raise ValueError("unsupported_enforcement_mode")

        money_limit = _coerce_optional_float(node_budget.get("node_money_limit"))
        compute_limit = _coerce_optional_float(node_budget.get("node_compute_limit"))
        if money_limit is not None and not declaration.supports_money_budget:
            raise ValueError("money_budget_not_supported")
        if compute_limit is not None and not declaration.supports_compute_budget:
            raise ValueError("compute_budget_not_supported")

        config = NodeBudgetConfigRecord(
            node_id=node_key,
            currency=currency,
            compute_unit=compute_unit,
            period=period,
            reset_policy=reset_policy,
            enforcement_mode=enforcement_mode,
            overcommit_enabled=bool(node_budget.get("overcommit_enabled", False)),
            shared_customer_pool=bool(node_budget.get("shared_customer_pool", False)),
            shared_provider_pool=bool(node_budget.get("shared_provider_pool", False)),
            node_money_limit=money_limit,
            node_compute_limit=compute_limit,
        )
        config = self._store.upsert_config(config)

        customer_records = self._normalize_allocations(
            node_id=node_key,
            kind="customer",
            allocations=customer_allocations or [],
            declaration=declaration,
        )
        provider_records = self._normalize_allocations(
            node_id=node_key,
            kind="provider",
            allocations=provider_allocations or [],
            declaration=declaration,
        )

        self._validate_allocation_totals(config=config, customer_records=customer_records, provider_records=provider_records)
        self._store.replace_allocations(node_key, "customer", customer_records)
        self._store.replace_allocations(node_key, "provider", provider_records)
        return self._store.bundle(node_key)

    def list_bundles(self) -> list[dict[str, Any]]:
        return self._store.list_bundles()

    def get_bundle(self, node_id: str) -> dict[str, Any]:
        bundle = self._store.bundle(node_id)
        if not bundle.get("declaration") and not bundle.get("node_budget"):
            raise ValueError("node_budget_not_found")
        return bundle

    def reserve_scheduler_budget(
        self,
        *,
        job_id: str,
        addon_id: str,
        cost_units: int,
        payload: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload_obj = payload if isinstance(payload, dict) else {}
        constraints_obj = constraints if isinstance(constraints, dict) else {}
        scope = payload_obj.get("budget_scope") if isinstance(payload_obj.get("budget_scope"), dict) else {}
        node_id = _clean_text(scope.get("node_id") or payload_obj.get("node_id") or constraints_obj.get("node_id"))
        if not node_id:
            return None
        config = self._store.get_config(node_id)
        if config is None:
            raise ValueError("node_budget_not_configured")

        existing = self._store.get_reservation_by_job(job_id)
        if existing is not None:
            return existing.to_dict()

        money_reserved = _coerce_optional_float(scope.get("money_estimate") or scope.get("money_reserved"))
        compute_reserved = _coerce_optional_float(scope.get("compute_units")) if scope.get("compute_units") is not None else float(cost_units)
        self._enforce_scheduler_scope_limits(
            config=config,
            node_id=node_id,
            customer_id=_clean_text(scope.get("customer_id") or payload_obj.get("customer_id"), lower=True) or None,
            provider_id=_clean_text(
                scope.get("provider") or scope.get("provider_id") or payload_obj.get("provider"),
                lower=True,
            )
            or None,
            requested_money=money_reserved,
            requested_compute=compute_reserved,
        )

        reservation = NodeBudgetReservationRecord(
            reservation_id=f"budget-reservation:{_clean_text(job_id)}",
            job_id=_clean_text(job_id),
            node_id=node_id,
            source="scheduler.queue",
            customer_id=_clean_text(scope.get("customer_id") or payload_obj.get("customer_id"), lower=True) or None,
            provider_id=_clean_text(
                scope.get("provider") or scope.get("provider_id") or payload_obj.get("provider"),
                lower=True,
            )
            or None,
            money_reserved=money_reserved,
            compute_reserved=compute_reserved,
        )
        return self._store.upsert_reservation(reservation).to_dict()

    def attach_scheduler_lease(self, *, job_id: str, lease_id: str | None) -> dict[str, Any] | None:
        record = self._store.get_reservation_by_job(job_id)
        if record is None:
            return None
        record.lease_id = _clean_text(lease_id) or None
        return self._store.upsert_reservation(record).to_dict()

    def finalize_scheduler_budget(
        self,
        *,
        job_id: str,
        actual_money_spend: float | None = None,
        actual_compute_spend: float | None = None,
    ) -> dict[str, Any] | None:
        record = self._store.get_reservation_by_job(job_id)
        if record is None:
            return None
        if record.state == "released":
            raise ValueError("budget_reservation_already_released")
        if record.state == "finalized":
            return record.to_dict()
        record.state = "finalized"
        record.money_actual = _coerce_optional_float(actual_money_spend) if actual_money_spend is not None else record.money_reserved
        record.compute_actual = (
            _coerce_optional_float(actual_compute_spend) if actual_compute_spend is not None else record.compute_reserved
        )
        record.finalized_at = _utcnow_iso()
        record.release_reason = None
        return self._store.upsert_reservation(record).to_dict()

    def release_scheduler_budget(self, *, job_id: str, reason: str) -> dict[str, Any] | None:
        record = self._store.get_reservation_by_job(job_id)
        if record is None:
            return None
        if record.state == "released":
            return record.to_dict()
        if record.state == "finalized":
            return record.to_dict()
        record.state = "released"
        record.release_reason = _clean_text(reason) or "released"
        record.released_at = _utcnow_iso()
        return self._store.upsert_reservation(record).to_dict()

    def get_reservation_by_job(self, job_id: str) -> dict[str, Any] | None:
        record = self._store.get_reservation_by_job(job_id)
        return record.to_dict() if record is not None else None

    def _committed_scope_amount(self, *, node_id: str, money: bool, customer_id: str | None = None, provider_id: str | None = None) -> float:
        total = 0.0
        for item in self._store.list_reservations(node_id=node_id):
            if item.state not in {"reserved", "finalized"}:
                continue
            if customer_id and item.customer_id != customer_id:
                continue
            if provider_id and item.provider_id != provider_id:
                continue
            value = item.money_reserved if money else item.compute_reserved
            if item.state == "finalized":
                actual_value = item.money_actual if money else item.compute_actual
                if actual_value is not None:
                    value = actual_value
            total += float(value or 0.0)
        return round(total, 6)

    def _enforce_scheduler_scope_limits(
        self,
        *,
        config: NodeBudgetConfigRecord,
        node_id: str,
        customer_id: str | None,
        provider_id: str | None,
        requested_money: float | None,
        requested_compute: float | None,
    ) -> None:
        if config.enforcement_mode != "hard_stop":
            return

        requested_money_value = float(requested_money or 0.0)
        requested_compute_value = float(requested_compute or 0.0)

        if config.node_money_limit is not None:
            committed = self._committed_scope_amount(node_id=node_id, money=True)
            if committed + requested_money_value > float(config.node_money_limit) + 1e-9:
                raise ValueError("node_money_budget_exceeded")
        if config.node_compute_limit is not None:
            committed = self._committed_scope_amount(node_id=node_id, money=False)
            if committed + requested_compute_value > float(config.node_compute_limit) + 1e-9:
                raise ValueError("node_compute_budget_exceeded")

        customer_allocations = {item.subject_id: item for item in self._store.list_allocations(node_id, kind="customer")}
        provider_allocations = {item.subject_id: item for item in self._store.list_allocations(node_id, kind="provider")}

        customer_record = customer_allocations.get(customer_id or "")
        if customer_id and customer_record is None and customer_allocations and not config.shared_customer_pool:
            raise ValueError("customer_budget_allocation_required")
        if customer_record is not None and not config.shared_customer_pool:
            if customer_record.money_limit is not None:
                committed = self._committed_scope_amount(node_id=node_id, money=True, customer_id=customer_record.subject_id)
                if committed + requested_money_value > float(customer_record.money_limit) + 1e-9:
                    raise ValueError("customer_money_budget_exceeded")
            if customer_record.compute_limit is not None:
                committed = self._committed_scope_amount(node_id=node_id, money=False, customer_id=customer_record.subject_id)
                if committed + requested_compute_value > float(customer_record.compute_limit) + 1e-9:
                    raise ValueError("customer_compute_budget_exceeded")

        provider_record = provider_allocations.get(provider_id or "")
        if provider_id and provider_record is None and provider_allocations and not config.shared_provider_pool:
            raise ValueError("provider_budget_allocation_required")
        if provider_record is not None and not config.shared_provider_pool:
            if provider_record.money_limit is not None:
                committed = self._committed_scope_amount(node_id=node_id, money=True, provider_id=provider_record.subject_id)
                if committed + requested_money_value > float(provider_record.money_limit) + 1e-9:
                    raise ValueError("provider_money_budget_exceeded")
            if provider_record.compute_limit is not None:
                committed = self._committed_scope_amount(node_id=node_id, money=False, provider_id=provider_record.subject_id)
                if committed + requested_compute_value > float(provider_record.compute_limit) + 1e-9:
                    raise ValueError("provider_compute_budget_exceeded")

    def _normalize_allocations(
        self,
        *,
        node_id: str,
        kind: str,
        allocations: list[dict[str, Any]],
        declaration: NodeBudgetCapabilityRecord,
    ) -> list[NodeBudgetAllocationRecord]:
        kind_key = _clean_text(kind, lower=True)
        if kind_key == "customer" and not declaration.supports_customer_allocations and allocations:
            raise ValueError("customer_budget_allocations_not_supported")
        if kind_key == "provider" and not declaration.supports_provider_allocations and allocations:
            raise ValueError("provider_budget_allocations_not_supported")

        records: list[NodeBudgetAllocationRecord] = []
        seen: set[str] = set()
        for item in allocations:
            if not isinstance(item, dict):
                continue
            subject_id = _clean_text(item.get("subject_id"), lower=True)
            if not subject_id or subject_id in seen:
                continue
            if kind_key == "provider" and declaration.supported_providers and subject_id not in set(declaration.supported_providers):
                raise ValueError("provider_budget_subject_not_supported")
            seen.add(subject_id)
            records.append(
                NodeBudgetAllocationRecord(
                    node_id=node_id,
                    kind=kind_key,
                    subject_id=subject_id,
                    money_limit=_coerce_optional_float(item.get("money_limit")),
                    compute_limit=_coerce_optional_float(item.get("compute_limit")),
                )
            )
        return records

    def _validate_allocation_totals(
        self,
        *,
        config: NodeBudgetConfigRecord,
        customer_records: list[NodeBudgetAllocationRecord],
        provider_records: list[NodeBudgetAllocationRecord],
    ) -> None:
        if config.overcommit_enabled:
            return

        def _sum_money(items: list[NodeBudgetAllocationRecord]) -> float:
            return round(sum(float(item.money_limit or 0) for item in items), 6)

        def _sum_compute(items: list[NodeBudgetAllocationRecord]) -> float:
            return round(sum(float(item.compute_limit or 0) for item in items), 6)

        if config.node_money_limit is not None:
            if _sum_money(customer_records) > float(config.node_money_limit) + 1e-9:
                raise ValueError("customer_budget_allocations_exceed_node_money_limit")
            if _sum_money(provider_records) > float(config.node_money_limit) + 1e-9:
                raise ValueError("provider_budget_allocations_exceed_node_money_limit")
        if config.node_compute_limit is not None:
            if _sum_compute(customer_records) > float(config.node_compute_limit) + 1e-9:
                raise ValueError("customer_budget_allocations_exceed_node_compute_limit")
            if _sum_compute(provider_records) > float(config.node_compute_limit) + 1e-9:
                raise ValueError("provider_budget_allocations_exceed_node_compute_limit")
