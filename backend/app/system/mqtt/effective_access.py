from __future__ import annotations

from dataclasses import dataclass

from .integration_models import MqttAddonGrant, MqttIntegrationState, MqttPrincipal
from .topic_families import BOOTSTRAP_TOPIC, canonical_reserved_prefixes, is_platform_reserved_topic


def _sorted_unique(items: list[str]) -> list[str]:
    return sorted({str(item).strip() for item in items if str(item).strip()})


@dataclass(frozen=True)
class MqttEffectiveAccessEntry:
    principal_id: str
    principal_type: str
    status: str
    publish_scopes: list[str]
    subscribe_scopes: list[str]
    reserved_prefix_denies: list[str]
    anonymous_bootstrap_only: bool = False
    generic_non_reserved_only: bool = False


class MqttEffectiveAccessCompiler:
    def __init__(self, *, bootstrap_topic: str = BOOTSTRAP_TOPIC, reserved_prefixes: list[str] | None = None) -> None:
        self._bootstrap_topic = str(bootstrap_topic).strip() or BOOTSTRAP_TOPIC
        self._reserved_prefixes = _sorted_unique(reserved_prefixes or canonical_reserved_prefixes())

    def compile(self, state: MqttIntegrationState) -> list[MqttEffectiveAccessEntry]:
        out: list[MqttEffectiveAccessEntry] = [
            MqttEffectiveAccessEntry(
                principal_id="anonymous",
                principal_type="anonymous",
                status="active",
                publish_scopes=[],
                subscribe_scopes=[self._bootstrap_topic],
                reserved_prefix_denies=["#"],
                anonymous_bootstrap_only=True,
                generic_non_reserved_only=False,
            )
        ]
        for principal in sorted(state.principals.values(), key=lambda item: item.principal_id):
            item = self._from_principal(principal, state)
            if item is not None:
                out.append(item)
        return out

    def inspect_principal(self, state: MqttIntegrationState, principal_id: str) -> MqttEffectiveAccessEntry | None:
        if principal_id == "anonymous":
            return self.compile(state)[0]
        principal = state.principals.get(principal_id)
        if principal is None:
            return None
        return self._from_principal(principal, state)

    def _from_principal(self, principal: MqttPrincipal, state: MqttIntegrationState) -> MqttEffectiveAccessEntry | None:
        if principal.status in {"revoked", "expired"}:
            return None
        if principal.noisy_state == "blocked":
            return MqttEffectiveAccessEntry(
                principal_id=principal.principal_id,
                principal_type=principal.principal_type,
                status=principal.status,
                publish_scopes=[],
                subscribe_scopes=[],
                reserved_prefix_denies=["#"],
                anonymous_bootstrap_only=False,
                generic_non_reserved_only=(principal.principal_type == "generic_user"),
            )
        publish_topics: list[str] = []
        subscribe_topics: list[str] = []
        reserved_denies: list[str] = []
        anonymous_bootstrap_only = False
        generic_non_reserved_only = False

        if principal.principal_type in {"synthia_addon", "synthia_node"}:
            grant = self._grant_for_principal(principal, state)
            if grant is None:
                return None
            publish_topics = _sorted_unique(list(grant.publish_topics))
            subscribe_topics = _sorted_unique(list(grant.subscribe_topics))
        elif principal.principal_type == "generic_user":
            mode = str(getattr(principal, "access_mode", "private") or "private").strip().lower()
            generic_non_reserved_only = mode == "non_reserved"
            publish_topics = _sorted_unique([topic for topic in principal.publish_topics if not is_platform_reserved_topic(topic)])
            subscribe_topics = _sorted_unique([topic for topic in principal.subscribe_topics if not is_platform_reserved_topic(topic)])
            if mode == "admin":
                publish_topics = ["#"]
                subscribe_topics = ["#"]
            elif mode == "non_reserved":
                publish_topics = ["#"]
                subscribe_topics = ["#"]
            if mode == "custom":
                custom_publish_topics = _sorted_unique(
                    [
                        topic
                        for topic in (principal.allowed_publish_topics or principal.allowed_topics)
                        if not is_platform_reserved_topic(topic)
                    ]
                )
                custom_subscribe_topics = _sorted_unique(
                    [
                        topic
                        for topic in (principal.allowed_subscribe_topics or principal.allowed_topics)
                        if not is_platform_reserved_topic(topic)
                    ]
                )
                if custom_publish_topics:
                    publish_topics = list(custom_publish_topics)
                if custom_subscribe_topics:
                    subscribe_topics = list(custom_subscribe_topics)
            reserved_denies = [] if mode == "admin" else list(self._reserved_prefixes)
        else:
            return None

        return MqttEffectiveAccessEntry(
            principal_id=principal.principal_id,
            principal_type=principal.principal_type,
            status=principal.status,
            publish_scopes=publish_topics,
            subscribe_scopes=subscribe_topics,
            reserved_prefix_denies=reserved_denies,
            anonymous_bootstrap_only=anonymous_bootstrap_only,
            generic_non_reserved_only=generic_non_reserved_only,
        )

    @staticmethod
    def _grant_for_principal(principal: MqttPrincipal, state: MqttIntegrationState) -> MqttAddonGrant | None:
        if principal.linked_addon_id:
            grant = state.active_grants.get(principal.linked_addon_id)
            if grant is None:
                return None
            if grant.status not in {"approved", "active", "provisioned"}:
                return None
            return grant
        return None
