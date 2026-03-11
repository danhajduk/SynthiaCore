from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .effective_access import MqttEffectiveAccessCompiler, MqttEffectiveAccessEntry
from .integration_models import MqttIntegrationState
from .topic_families import BOOTSTRAP_TOPIC, canonical_reserved_prefixes


DEFAULT_RESERVED_PREFIXES: tuple[str, ...] = tuple(canonical_reserved_prefixes())
DEFAULT_BOOTSTRAP_TOPIC = BOOTSTRAP_TOPIC


@dataclass(frozen=True)
class CompiledAclRule:
    principal_id: str
    action: str
    topic: str
    effect: str


@dataclass(frozen=True)
class MqttAclCompilationResult:
    rules: list[CompiledAclRule]
    acl_text: str
    effective_access: list[MqttEffectiveAccessEntry]


@dataclass(frozen=True)
class NormalizedEffectiveAccess:
    principal_id: str
    principal_type: str
    access_mode: str | None
    bootstrap_only: bool
    all_non_reserved: bool
    read_rules: list[str]
    write_rules: list[str]
    deny_rules: list[str]
    normalization_notes: list[str]


def _sorted_unique(items: Iterable[str]) -> list[str]:
    return sorted({str(item).strip() for item in items if str(item).strip()})


def _sanitize_username(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip())
    clean = clean.strip("_.-")
    return clean[:64] if clean else "mqtt_user"


class MqttAclCompiler:
    def __init__(
        self,
        *,
        bootstrap_topic: str = DEFAULT_BOOTSTRAP_TOPIC,
        reserved_prefixes: Iterable[str] | None = None,
    ) -> None:
        self._bootstrap_topic = str(bootstrap_topic or DEFAULT_BOOTSTRAP_TOPIC).strip() or DEFAULT_BOOTSTRAP_TOPIC
        self._reserved = _sorted_unique(reserved_prefixes or DEFAULT_RESERVED_PREFIXES)
        self._effective_access = MqttEffectiveAccessCompiler(
            bootstrap_topic=self._bootstrap_topic,
            reserved_prefixes=list(self._reserved),
        )

    def compile(self, state: MqttIntegrationState) -> MqttAclCompilationResult:
        entries = self._effective_access.compile(state)
        normalized_model = self._normalize_effective_access_model(self._build_effective_access_model(state, entries))
        rules = self._render_mosquitto_rules(normalized_model)
        normalized = self._normalize_rules(rules)
        return MqttAclCompilationResult(rules=normalized, acl_text=self._to_acl_text(state, normalized), effective_access=entries)

    def compile_effective_access(self, state: MqttIntegrationState) -> list[MqttEffectiveAccessEntry]:
        return self._effective_access.compile(state)

    def compile_normalized_effective_access(self, state: MqttIntegrationState) -> list[NormalizedEffectiveAccess]:
        entries = self._effective_access.compile(state)
        return self._normalize_effective_access_model(self._build_effective_access_model(state, entries))

    def inspect_effective_access(self, state: MqttIntegrationState, principal_id: str) -> MqttEffectiveAccessEntry | None:
        return self._effective_access.inspect_principal(state, principal_id)

    def inspect_normalized_effective_access(self, state: MqttIntegrationState, principal_id: str) -> NormalizedEffectiveAccess | None:
        model = self.compile_normalized_effective_access(state)
        for item in model:
            if item.principal_id == principal_id:
                return item
        return None

    @staticmethod
    def _build_effective_access_model(state: MqttIntegrationState, entries: list[MqttEffectiveAccessEntry]) -> list[NormalizedEffectiveAccess]:
        model: list[NormalizedEffectiveAccess] = []
        for entry in entries:
            deny_rules: list[str] = []
            notes: list[str] = []
            access_mode: str | None = None
            if entry.principal_id == "anonymous":
                # Anonymous baseline is already default-deny in Mosquitto ACL evaluation.
                # Emit only explicit bootstrap read allow to avoid broad deny collisions.
                deny_rules = []
                access_mode = "bootstrap_only"
            elif entry.principal_type == "generic_user":
                deny_rules = list(entry.reserved_prefix_denies)
                principal = state.principals.get(entry.principal_id)
                access_mode = str(getattr(principal, "access_mode", "private") or "private").strip().lower()
                if access_mode == "non_reserved":
                    notes.append("render_strategy:allow_all_with_reserved_denies")
                if access_mode == "admin":
                    notes.append("render_strategy:full_access")
            model.append(
                NormalizedEffectiveAccess(
                    principal_id=entry.principal_id,
                    principal_type=entry.principal_type,
                    access_mode=access_mode,
                    bootstrap_only=bool(entry.anonymous_bootstrap_only),
                    all_non_reserved=bool(entry.generic_non_reserved_only),
                    read_rules=_sorted_unique(entry.subscribe_scopes),
                    write_rules=_sorted_unique(entry.publish_scopes),
                    deny_rules=_sorted_unique(deny_rules),
                    normalization_notes=notes,
                )
            )
        return model

    @staticmethod
    def _normalize_effective_access_model(entries: list[NormalizedEffectiveAccess]) -> list[NormalizedEffectiveAccess]:
        normalized: list[NormalizedEffectiveAccess] = []
        for entry in entries:
            normalized.append(
                NormalizedEffectiveAccess(
                    principal_id=entry.principal_id,
                    principal_type=entry.principal_type,
                    access_mode=entry.access_mode,
                    bootstrap_only=bool(entry.bootstrap_only),
                    all_non_reserved=bool(entry.all_non_reserved),
                    read_rules=_sorted_unique(entry.read_rules),
                    write_rules=_sorted_unique(entry.write_rules),
                    deny_rules=_sorted_unique(entry.deny_rules),
                    normalization_notes=_sorted_unique(entry.normalization_notes),
                )
            )
        return normalized

    @staticmethod
    def _render_mosquitto_rules(entries: list[NormalizedEffectiveAccess]) -> list[CompiledAclRule]:
        rules: list[CompiledAclRule] = []
        for entry in entries:
            if entry.principal_id == "anonymous":
                for topic in entry.read_rules:
                    rules.append(CompiledAclRule("anonymous", "subscribe", topic, "allow"))
                for topic in entry.deny_rules:
                    rules.append(CompiledAclRule("anonymous", "publish", topic, "deny"))
                    rules.append(CompiledAclRule("anonymous", "subscribe", topic, "deny"))
                continue
            for topic in entry.write_rules:
                rules.append(CompiledAclRule(entry.principal_id, "publish", topic, "allow"))
            for topic in entry.read_rules:
                rules.append(CompiledAclRule(entry.principal_id, "subscribe", topic, "allow"))
            for prefix in entry.deny_rules:
                rules.append(CompiledAclRule(entry.principal_id, "publish", prefix, "deny"))
                rules.append(CompiledAclRule(entry.principal_id, "subscribe", prefix, "deny"))
        return rules

    def _to_acl_text(self, state: MqttIntegrationState, rules: list[CompiledAclRule]) -> str:
        lines: list[str] = []
        lines.append("# generated by synthia core mqtt acl compiler")
        anonymous_rules = sorted(
            [rule for rule in rules if rule.principal_id == "anonymous"],
            key=lambda item: (item.effect, item.action, item.topic),
        )
        for rule in anonymous_rules:
            acl = self._to_mosquitto_acl_line(rule)
            if acl is not None:
                lines.append(acl)

        principal_ids = sorted({rule.principal_id for rule in rules if rule.principal_id != "anonymous"})
        for principal_id in principal_ids:
            username = self._principal_username(state, principal_id)
            if not username:
                continue
            lines.append("")
            lines.append(f"user {username}")
            principal_rules = sorted(
                [rule for rule in rules if rule.principal_id == principal_id],
                key=lambda item: (item.effect, item.action, item.topic),
            )
            for rule in principal_rules:
                acl = self._to_mosquitto_acl_line(rule)
                if acl is not None:
                    lines.append(acl)
        return "\n".join(lines) + "\n"

    @staticmethod
    def _to_mosquitto_acl_line(rule: CompiledAclRule) -> str | None:
        if rule.effect == "deny":
            return f"topic deny {rule.topic}"
        if rule.action == "readwrite":
            return f"topic readwrite {rule.topic}"
        if rule.action == "publish":
            return f"topic write {rule.topic}"
        if rule.action == "subscribe":
            return f"topic read {rule.topic}"
        return None

    @classmethod
    def _normalize_rules(cls, rules: list[CompiledAclRule]) -> list[CompiledAclRule]:
        deduped = sorted(set(rules), key=lambda item: (item.principal_id, item.effect, item.action, item.topic))
        collapsed_denies = cls._collapse_redundant_denies(deduped)
        merged_readwrite = cls._merge_readwrite_rules(collapsed_denies)
        action_collapsed_denies = cls._collapse_duplicate_deny_actions(merged_readwrite)
        return sorted(set(action_collapsed_denies), key=lambda item: (item.principal_id, item.effect, item.action, item.topic))

    @classmethod
    def _collapse_redundant_denies(cls, rules: list[CompiledAclRule]) -> list[CompiledAclRule]:
        by_key: dict[tuple[str, str], list[CompiledAclRule]] = {}
        for rule in rules:
            if rule.effect != "deny":
                continue
            key = (rule.principal_id, rule.action)
            by_key.setdefault(key, []).append(rule)
        keep: set[CompiledAclRule] = set(rules)
        for key, deny_rules in by_key.items():
            topics = sorted({rule.topic for rule in deny_rules}, key=lambda topic: (len(topic), topic))
            for topic in topics:
                for parent in topics:
                    if parent == topic:
                        continue
                    if cls._is_deny_covered_by_existing(parent, topic):
                        rule = CompiledAclRule(principal_id=key[0], action=key[1], topic=topic, effect="deny")
                        if rule in keep:
                            keep.remove(rule)
                        break
        return sorted(keep, key=lambda item: (item.principal_id, item.effect, item.action, item.topic))

    @staticmethod
    def _topic_covers(parent: str, child: str) -> bool:
        p = str(parent or "").strip()
        c = str(child or "").strip()
        if not p or not c:
            return False
        if p == "#":
            return True
        if p.endswith("/#"):
            prefix = p[:-1]
            return c.startswith(prefix)
        return p == c

    @classmethod
    def _is_deny_covered_by_existing(cls, existing: str, candidate: str) -> bool:
        return cls._topic_covers(existing, candidate)

    @staticmethod
    def _merge_readwrite_rules(rules: list[CompiledAclRule]) -> list[CompiledAclRule]:
        allow_publish = {(rule.principal_id, rule.topic) for rule in rules if rule.effect == "allow" and rule.action == "publish"}
        allow_subscribe = {(rule.principal_id, rule.topic) for rule in rules if rule.effect == "allow" and rule.action == "subscribe"}
        merged_targets = allow_publish & allow_subscribe
        out: list[CompiledAclRule] = []
        for rule in rules:
            key = (rule.principal_id, rule.topic)
            if key in merged_targets and rule.effect == "allow" and rule.action in {"publish", "subscribe"}:
                continue
            out.append(rule)
        for principal_id, topic in sorted(merged_targets):
            out.append(CompiledAclRule(principal_id=principal_id, action="readwrite", topic=topic, effect="allow"))
        return out

    @staticmethod
    def _collapse_duplicate_deny_actions(rules: list[CompiledAclRule]) -> list[CompiledAclRule]:
        out: list[CompiledAclRule] = []
        seen_deny_topics: set[tuple[str, str]] = set()
        for rule in rules:
            if rule.effect != "deny":
                out.append(rule)
                continue
            key = (rule.principal_id, rule.topic)
            if key in seen_deny_topics:
                continue
            seen_deny_topics.add(key)
            out.append(CompiledAclRule(principal_id=rule.principal_id, action="publish", topic=rule.topic, effect="deny"))
        return out

    @staticmethod
    def _principal_username(state: MqttIntegrationState, principal_id: str) -> str:
        principal = state.principals.get(principal_id)
        if principal is None:
            return _sanitize_username(principal_id.replace(":", "_"))
        username = str(principal.username or "").strip()
        if username:
            return _sanitize_username(username)
        prefix = "sx"
        if principal.principal_type == "generic_user":
            prefix = "gu"
        elif principal.principal_type == "synthia_node":
            prefix = "sn"
        return _sanitize_username(f"{prefix}_{principal.logical_identity}")
