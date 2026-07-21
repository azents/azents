"""Resolve model-specific client tool compatibility profiles."""

import dataclasses
import enum
from collections.abc import Sequence

from azents.core.enums import LLMModelDeveloper, LLMProvider


class ClientToolProfile(enum.StrEnum):
    """Code-owned model compatibility profiles for client-executed tools."""

    V4A_APPLY_PATCH_FUNCTION = "v4a_apply_patch_function"
    V4A_APPLY_PATCH_PLAINTEXT_CUSTOM = "v4a_apply_patch_plaintext_custom"


@dataclasses.dataclass(frozen=True)
class ClientToolRoute:
    """Credential-free route facts used for pre-dispatch dialect selection."""

    provider: LLMProvider
    adapter: str
    native_format: str
    official_openai_endpoint: bool
    api_key_available: bool

    def __post_init__(self) -> None:
        """Normalize route facts and reject invalid rollout configuration."""
        object.__setattr__(self, "adapter", _normalize_required(self.adapter))
        object.__setattr__(
            self,
            "native_format",
            _normalize_required(self.native_format),
        )


class ClientToolCompatibilityMatchKind(enum.IntEnum):
    """Compatibility rule specificity in ascending precedence order."""

    MODEL_FAMILY = 1
    EXACT_MODEL = 2


@dataclasses.dataclass(frozen=True)
class ClientToolCompatibilityKey:
    """Normalized model identity used for client tool compatibility."""

    model_identifier: str
    model_developer: LLMModelDeveloper | None
    model_family: str | None

    def __post_init__(self) -> None:
        """Normalize catalog-provided model identity fields."""
        object.__setattr__(
            self,
            "model_identifier",
            _normalize_required(self.model_identifier),
        )
        object.__setattr__(
            self,
            "model_family",
            _normalize_optional(self.model_family),
        )


@dataclasses.dataclass(frozen=True)
class ClientToolCompatibilityRule:
    """One code-owned grant or deny rule for a client tool profile."""

    rule_id: str
    profile: ClientToolProfile
    model_developer: LLMModelDeveloper
    enabled: bool
    exact_model_identifier: str | None
    model_family_root: str | None

    def __post_init__(self) -> None:
        """Normalize and validate one compatibility rule."""
        object.__setattr__(self, "rule_id", _normalize_required(self.rule_id))
        object.__setattr__(
            self,
            "exact_model_identifier",
            _normalize_optional(self.exact_model_identifier),
        )
        object.__setattr__(
            self,
            "model_family_root",
            _normalize_optional(self.model_family_root),
        )
        if (self.exact_model_identifier is None) == (self.model_family_root is None):
            raise ValueError(
                "Client tool compatibility rules require exactly one model matcher"
            )

    @property
    def match_kind(self) -> ClientToolCompatibilityMatchKind:
        """Return deterministic rule specificity."""
        if self.exact_model_identifier is not None:
            return ClientToolCompatibilityMatchKind.EXACT_MODEL
        return ClientToolCompatibilityMatchKind.MODEL_FAMILY

    def matches(self, key: ClientToolCompatibilityKey) -> bool:
        """Return whether this rule applies to one normalized model snapshot."""
        if key.model_developer is not self.model_developer:
            return False
        if self.exact_model_identifier is not None:
            return key.model_identifier == self.exact_model_identifier
        family = key.model_family
        root = self.model_family_root
        if family is None or root is None:
            return False
        return family == root or family.startswith(f"{root}-")


class ClientToolCompatibilityConflictError(ValueError):
    """Raised when equally specific rules select one profile ambiguously."""


class ClientToolCompatibilityRegistry:
    """Resolve client tool profiles from normalized model snapshots."""

    def __init__(self, rules: Sequence[ClientToolCompatibilityRule]) -> None:
        self.rules = tuple(rules)
        _validate_no_same_specificity_overlap(self.rules)

    def resolve(
        self,
        key: ClientToolCompatibilityKey,
    ) -> frozenset[ClientToolProfile]:
        """Return the immutable set of enabled profiles for one model."""
        enabled: set[ClientToolProfile] = set()
        for profile in ClientToolProfile:
            matching = [
                rule
                for rule in self.rules
                if rule.profile is profile and rule.matches(key)
            ]
            if not matching:
                continue
            highest = max(rule.match_kind for rule in matching)
            selected = [rule for rule in matching if rule.match_kind is highest]
            if len(selected) != 1:
                rule_ids = ", ".join(sorted(rule.rule_id for rule in selected))
                raise ClientToolCompatibilityConflictError(
                    "Multiple client tool compatibility rules matched at the same "
                    f"specificity for {profile.value}: {rule_ids}"
                )
            if selected[0].enabled:
                enabled.add(profile)
        return frozenset(enabled)


def build_default_client_tool_compatibility_registry() -> (
    ClientToolCompatibilityRegistry
):
    """Build the reviewed default client tool compatibility registry."""
    return ClientToolCompatibilityRegistry(
        (
            ClientToolCompatibilityRule(
                rule_id="openai-gpt-v4a-apply-patch-function",
                profile=ClientToolProfile.V4A_APPLY_PATCH_FUNCTION,
                model_developer=LLMModelDeveloper.OPENAI,
                enabled=True,
                exact_model_identifier=None,
                model_family_root="gpt",
            ),
        )
    )


def resolve_client_tool_profiles(
    *,
    model_identifier: str,
    model_developer: LLMModelDeveloper | None,
    model_family: str | None,
    route: ClientToolRoute,
) -> frozenset[ClientToolProfile]:
    """Resolve one pre-dispatch client-tool dialect selection."""
    profiles = build_default_client_tool_compatibility_registry().resolve(
        ClientToolCompatibilityKey(
            model_identifier=model_identifier,
            model_developer=model_developer,
            model_family=model_family,
        )
    )
    if ClientToolProfile.V4A_APPLY_PATCH_FUNCTION not in profiles:
        return frozenset()
    key = ClientToolCompatibilityKey(
        model_identifier=model_identifier,
        model_developer=model_developer,
        model_family=model_family,
    )
    if _custom_apply_patch_transport_eligible(key=key, route=route):
        return frozenset({ClientToolProfile.V4A_APPLY_PATCH_PLAINTEXT_CUSTOM})
    if _function_apply_patch_transport_eligible(route):
        return frozenset({ClientToolProfile.V4A_APPLY_PATCH_FUNCTION})
    return frozenset()


def supports_historical_plaintext_custom_apply_patch(
    *,
    model_identifier: str,
    model_developer: LLMModelDeveloper | None,
    model_family: str | None,
    route: ClientToolRoute,
) -> bool:
    """Return whether one route can encode existing custom apply-patch history."""
    key = ClientToolCompatibilityKey(
        model_identifier=model_identifier,
        model_developer=model_developer,
        model_family=model_family,
    )
    return _custom_apply_patch_transport_supported(key=key, route=route)


def _custom_apply_patch_transport_eligible(
    *,
    key: ClientToolCompatibilityKey,
    route: ClientToolRoute,
) -> bool:
    """Return whether one exact reviewed OpenAI custom route is selected."""
    return _custom_apply_patch_transport_supported(key=key, route=route)


def _custom_apply_patch_transport_supported(
    *,
    key: ClientToolCompatibilityKey,
    route: ClientToolRoute,
) -> bool:
    """Return whether one exact reviewed route can encode custom history."""
    return (
        route.provider is LLMProvider.OPENAI
        and route.adapter == "openai"
        and route.native_format == "responses"
        and route.official_openai_endpoint
        and route.api_key_available
        and key.model_identifier == "gpt-5.1"
    )


def _function_apply_patch_transport_eligible(route: ClientToolRoute) -> bool:
    """Return whether the selected route has reviewed JSON function transport."""
    if route.native_format != "responses":
        return False
    if route.provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        return route.adapter == "openai"
    return route.provider is LLMProvider.OPENROUTER and route.adapter == "litellm"


def _validate_no_same_specificity_overlap(
    rules: Sequence[ClientToolCompatibilityRule],
) -> None:
    """Reject ambiguous compatibility rules before request preparation."""
    seen_rule_ids: set[str] = set()
    for index, rule in enumerate(rules):
        if rule.rule_id in seen_rule_ids:
            raise ClientToolCompatibilityConflictError(
                f"Duplicate client tool compatibility rule ID: {rule.rule_id}"
            )
        seen_rule_ids.add(rule.rule_id)
        for other in rules[index + 1 :]:
            if _rules_overlap_at_same_specificity(rule, other):
                raise ClientToolCompatibilityConflictError(
                    "Client tool compatibility rules overlap at the same "
                    f"specificity: {rule.rule_id}, {other.rule_id}"
                )


def _rules_overlap_at_same_specificity(
    left: ClientToolCompatibilityRule,
    right: ClientToolCompatibilityRule,
) -> bool:
    """Return whether two rules can ambiguously select one profile."""
    if (
        left.profile is not right.profile
        or left.match_kind is not right.match_kind
        or left.model_developer is not right.model_developer
    ):
        return False
    if left.match_kind is ClientToolCompatibilityMatchKind.EXACT_MODEL:
        return left.exact_model_identifier == right.exact_model_identifier
    left_root = left.model_family_root
    right_root = right.model_family_root
    if left_root is None or right_root is None:
        return False
    return (
        left_root == right_root
        or left_root.startswith(f"{right_root}-")
        or right_root.startswith(f"{left_root}-")
    )


def _normalize_required(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("Client tool compatibility values must be non-empty")
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None
