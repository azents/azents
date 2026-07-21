"""Resolve model and adapter profiles for client tool wire variants."""

import dataclasses
import enum
from collections.abc import Sequence

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.engine.client_tools import ClientToolWireDialect

_SUPPORTED_WIRE_DIALECTS: frozenset[ClientToolWireDialect] = frozenset(
    {"json_function", "plaintext_custom"}
)


class ClientToolModelProfile(enum.StrEnum):
    """Code-owned semantic model profiles for client-executed tools."""

    V4A_PATCH = "v4a_patch"


@dataclasses.dataclass(frozen=True)
class ClientToolRoute:
    """Credential-free route facts used for pre-dispatch variant selection."""

    provider: LLMProvider
    adapter: str
    native_format: str

    def __post_init__(self) -> None:
        """Normalize route facts."""
        object.__setattr__(self, "adapter", _normalize_required(self.adapter))
        object.__setattr__(
            self,
            "native_format",
            _normalize_required(self.native_format),
        )


class ClientToolModelCompatibilityMatchKind(enum.IntEnum):
    """Model compatibility rule specificity in ascending precedence order."""

    MODEL_FAMILY = 1
    EXACT_MODEL = 2


@dataclasses.dataclass(frozen=True)
class ClientToolModelCompatibilityKey:
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
class ClientToolModelCompatibilityRule:
    """One code-owned grant or deny rule for a semantic model profile."""

    rule_id: str
    profile: ClientToolModelProfile
    model_developer: LLMModelDeveloper
    enabled: bool
    exact_model_identifier: str | None
    model_family_root: str | None

    def __post_init__(self) -> None:
        """Normalize and validate one model compatibility rule."""
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
                "Client tool model compatibility rules require exactly one matcher"
            )

    @property
    def match_kind(self) -> ClientToolModelCompatibilityMatchKind:
        """Return deterministic rule specificity."""
        if self.exact_model_identifier is not None:
            return ClientToolModelCompatibilityMatchKind.EXACT_MODEL
        return ClientToolModelCompatibilityMatchKind.MODEL_FAMILY

    def matches(self, key: ClientToolModelCompatibilityKey) -> bool:
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


class ClientToolModelCompatibilityConflictError(ValueError):
    """Raised when model rules select one profile ambiguously."""


class ClientToolModelCompatibilityRegistry:
    """Resolve semantic client tool profiles from normalized model snapshots."""

    def __init__(self, rules: Sequence[ClientToolModelCompatibilityRule]) -> None:
        self.rules = tuple(rules)
        _validate_no_model_rule_overlap(self.rules)

    def resolve(
        self,
        key: ClientToolModelCompatibilityKey,
    ) -> frozenset[ClientToolModelProfile]:
        """Return the immutable set of enabled semantic profiles for one model."""
        enabled: set[ClientToolModelProfile] = set()
        for profile in ClientToolModelProfile:
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
                raise ClientToolModelCompatibilityConflictError(
                    "Multiple client tool model compatibility rules matched at the "
                    f"same specificity for {profile.value}: {rule_ids}"
                )
            if selected[0].enabled:
                enabled.add(profile)
        return frozenset(enabled)


@dataclasses.dataclass(frozen=True)
class ClientToolAdapterModelProfilePreference:
    """Dialect preference selected for one semantic model profile."""

    model_profile: ClientToolModelProfile
    wire_dialects: tuple[ClientToolWireDialect, ...]

    def __post_init__(self) -> None:
        """Validate and freeze the declared preference order."""
        object.__setattr__(
            self,
            "wire_dialects",
            _normalize_wire_dialects(self.wire_dialects),
        )


class ClientToolAdapterProfileMatchKind(enum.IntEnum):
    """Adapter profile specificity in ascending precedence order."""

    ADAPTER = 1
    PROVIDER_ADAPTER = 2


@dataclasses.dataclass(frozen=True)
class ClientToolAdapterProfile:
    """Wire-variant preferences for one normalized provider route."""

    profile_id: str
    provider: LLMProvider | None
    adapter: str
    native_format: str
    default_wire_dialects: tuple[ClientToolWireDialect, ...]
    model_profile_preferences: tuple[ClientToolAdapterModelProfilePreference, ...]

    def __post_init__(self) -> None:
        """Normalize and validate one adapter profile."""
        object.__setattr__(self, "profile_id", _normalize_required(self.profile_id))
        object.__setattr__(self, "adapter", _normalize_required(self.adapter))
        object.__setattr__(
            self,
            "native_format",
            _normalize_required(self.native_format),
        )
        object.__setattr__(
            self,
            "default_wire_dialects",
            _normalize_wire_dialects(self.default_wire_dialects),
        )
        preferences = tuple(self.model_profile_preferences)
        model_profiles = [preference.model_profile for preference in preferences]
        if len(model_profiles) != len(set(model_profiles)):
            raise ValueError(
                "Client tool adapter profiles cannot repeat a model profile"
            )
        object.__setattr__(self, "model_profile_preferences", preferences)

    @property
    def match_kind(self) -> ClientToolAdapterProfileMatchKind:
        """Return deterministic route specificity."""
        if self.provider is not None:
            return ClientToolAdapterProfileMatchKind.PROVIDER_ADAPTER
        return ClientToolAdapterProfileMatchKind.ADAPTER

    def matches(self, route: ClientToolRoute) -> bool:
        """Return whether this profile applies to one normalized route."""
        return (
            (self.provider is None or route.provider is self.provider)
            and route.adapter == self.adapter
            and route.native_format == self.native_format
        )

    def wire_dialects_for(
        self,
        model_profile: ClientToolModelProfile | None,
    ) -> tuple[ClientToolWireDialect, ...]:
        """Return the ordered dialect preference for one tool profile."""
        if model_profile is None:
            return self.default_wire_dialects
        for preference in self.model_profile_preferences:
            if preference.model_profile is model_profile:
                return preference.wire_dialects
        return ()

    def supports_wire_dialect(self, wire_dialect: ClientToolWireDialect) -> bool:
        """Return whether any selection path on this route supports a dialect."""
        return wire_dialect in self.default_wire_dialects or any(
            wire_dialect in preference.wire_dialects
            for preference in self.model_profile_preferences
        )


class ClientToolAdapterProfileConflictError(ValueError):
    """Raised when adapter profiles match one route ambiguously."""


class ClientToolAdapterProfileRegistry:
    """Resolve one adapter profile from normalized provider route facts."""

    def __init__(self, profiles: Sequence[ClientToolAdapterProfile]) -> None:
        self.profiles = tuple(profiles)
        _validate_no_adapter_profile_overlap(self.profiles)

    def resolve(self, route: ClientToolRoute) -> ClientToolAdapterProfile | None:
        """Return the highest-specificity adapter profile for one route."""
        matching = [profile for profile in self.profiles if profile.matches(route)]
        if not matching:
            return None
        highest = max(profile.match_kind for profile in matching)
        selected = [profile for profile in matching if profile.match_kind is highest]
        if len(selected) != 1:
            profile_ids = ", ".join(sorted(profile.profile_id for profile in selected))
            raise ClientToolAdapterProfileConflictError(
                "Multiple client tool adapter profiles matched at the same "
                f"specificity: {profile_ids}"
            )
        return selected[0]


def build_default_client_tool_model_compatibility_registry() -> (
    ClientToolModelCompatibilityRegistry
):
    """Build the reviewed default semantic model compatibility registry."""
    return ClientToolModelCompatibilityRegistry(
        (
            ClientToolModelCompatibilityRule(
                rule_id="openai-gpt-v4a-patch",
                profile=ClientToolModelProfile.V4A_PATCH,
                model_developer=LLMModelDeveloper.OPENAI,
                enabled=True,
                exact_model_identifier=None,
                model_family_root="gpt",
            ),
        )
    )


def build_default_client_tool_adapter_profile_registry() -> (
    ClientToolAdapterProfileRegistry
):
    """Build the reviewed default adapter wire-variant registry."""
    v4a_profile = ClientToolModelProfile.V4A_PATCH
    return ClientToolAdapterProfileRegistry(
        (
            ClientToolAdapterProfile(
                profile_id="native-openai-responses",
                provider=None,
                adapter="openai",
                native_format="responses",
                default_wire_dialects=("json_function",),
                model_profile_preferences=(
                    ClientToolAdapterModelProfilePreference(
                        model_profile=v4a_profile,
                        wire_dialects=("plaintext_custom", "json_function"),
                    ),
                ),
            ),
            ClientToolAdapterProfile(
                profile_id="generic-litellm-responses",
                provider=None,
                adapter="litellm",
                native_format="responses",
                default_wire_dialects=("json_function",),
                model_profile_preferences=(),
            ),
            ClientToolAdapterProfile(
                profile_id="openrouter-litellm-responses",
                provider=LLMProvider.OPENROUTER,
                adapter="litellm",
                native_format="responses",
                default_wire_dialects=("json_function",),
                model_profile_preferences=(
                    ClientToolAdapterModelProfilePreference(
                        model_profile=v4a_profile,
                        wire_dialects=("json_function",),
                    ),
                ),
            ),
        )
    )


def resolve_client_tool_model_profiles(
    *,
    model_identifier: str,
    model_developer: LLMModelDeveloper | None,
    model_family: str | None,
) -> frozenset[ClientToolModelProfile]:
    """Resolve semantic client-tool profiles for one selected model snapshot."""
    return build_default_client_tool_model_compatibility_registry().resolve(
        ClientToolModelCompatibilityKey(
            model_identifier=model_identifier,
            model_developer=model_developer,
            model_family=model_family,
        )
    )


def resolve_client_tool_adapter_profile(
    *,
    route: ClientToolRoute,
) -> ClientToolAdapterProfile | None:
    """Resolve one adapter profile for pre-dispatch variant selection."""
    return build_default_client_tool_adapter_profile_registry().resolve(route)


def _validate_no_model_rule_overlap(
    rules: Sequence[ClientToolModelCompatibilityRule],
) -> None:
    """Reject ambiguous model compatibility rules before preparation."""
    seen_rule_ids: set[str] = set()
    for index, rule in enumerate(rules):
        if rule.rule_id in seen_rule_ids:
            raise ClientToolModelCompatibilityConflictError(
                f"Duplicate client tool model compatibility rule ID: {rule.rule_id}"
            )
        seen_rule_ids.add(rule.rule_id)
        for other in rules[index + 1 :]:
            if _model_rules_overlap_at_same_specificity(rule, other):
                raise ClientToolModelCompatibilityConflictError(
                    "Client tool model compatibility rules overlap at the same "
                    f"specificity: {rule.rule_id}, {other.rule_id}"
                )


def _model_rules_overlap_at_same_specificity(
    left: ClientToolModelCompatibilityRule,
    right: ClientToolModelCompatibilityRule,
) -> bool:
    """Return whether two model rules can ambiguously select one profile."""
    if (
        left.profile is not right.profile
        or left.match_kind is not right.match_kind
        or left.model_developer is not right.model_developer
    ):
        return False
    if left.match_kind is ClientToolModelCompatibilityMatchKind.EXACT_MODEL:
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


def _validate_no_adapter_profile_overlap(
    profiles: Sequence[ClientToolAdapterProfile],
) -> None:
    """Reject duplicate IDs and equally specific route overlaps."""
    seen_profile_ids: set[str] = set()
    for index, profile in enumerate(profiles):
        if profile.profile_id in seen_profile_ids:
            raise ClientToolAdapterProfileConflictError(
                f"Duplicate client tool adapter profile ID: {profile.profile_id}"
            )
        seen_profile_ids.add(profile.profile_id)
        for other in profiles[index + 1 :]:
            if _adapter_profiles_overlap_at_same_specificity(profile, other):
                raise ClientToolAdapterProfileConflictError(
                    "Client tool adapter profiles overlap at the same specificity: "
                    f"{profile.profile_id}, {other.profile_id}"
                )


def _adapter_profiles_overlap_at_same_specificity(
    left: ClientToolAdapterProfile,
    right: ClientToolAdapterProfile,
) -> bool:
    """Return whether two adapter profiles can match one route ambiguously."""
    return (
        left.match_kind is right.match_kind
        and left.provider is right.provider
        and left.adapter == right.adapter
        and left.native_format == right.native_format
    )


def _normalize_wire_dialects(
    values: Sequence[ClientToolWireDialect],
) -> tuple[ClientToolWireDialect, ...]:
    """Validate one non-empty dialect preference without changing its order."""
    normalized = tuple(values)
    if not normalized:
        raise ValueError("Client tool wire-dialect preferences must be non-empty")
    invalid = set(normalized) - _SUPPORTED_WIRE_DIALECTS
    if invalid:
        names = ", ".join(sorted(invalid))
        raise ValueError(f"Unsupported client tool wire dialects: {names}")
    if len(normalized) != len(set(normalized)):
        raise ValueError(
            "Client tool wire-dialect preferences cannot contain duplicates"
        )
    return normalized


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
