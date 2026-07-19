"""Resolve provider-request tool declaration compatibility budgets."""

import dataclasses
import datetime
import enum
from collections.abc import Sequence
from typing import assert_never

from azents.core.enums import LLMModelDeveloper, LLMProvider


class ToolDeclarationCountingScope(enum.StrEnum):
    """Provider request declarations counted by one compatibility rule."""

    TOTAL_TOOLS = "total_tools"
    FUNCTION_DECLARATIONS = "function_declarations"


class ToolCompatibilityMatchKind(enum.IntEnum):
    """Compatibility rule specificity in ascending precedence order."""

    ENDPOINT = 1
    MODEL_FAMILY = 2
    EXACT_MODEL = 3


@dataclasses.dataclass(frozen=True)
class ToolRequestCompatibilityKey:
    """Normalized identity of one provider request lowering path."""

    provider: LLMProvider
    adapter: str
    native_format: str
    model_identifier: str
    model_developer: LLMModelDeveloper | None
    model_family: str | None

    def __post_init__(self) -> None:
        """Normalize free-form request identity fields."""
        object.__setattr__(self, "adapter", _normalize_required(self.adapter))
        object.__setattr__(
            self,
            "native_format",
            _normalize_required(self.native_format),
        )
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
class ToolCompatibilityRuleSource:
    """Reviewed provenance for one provider compatibility rule."""

    urls: tuple[str, ...]
    verified_on: datetime.date
    note: str | None

    def __post_init__(self) -> None:
        """Reject incomplete source metadata."""
        if not self.urls or any(not url.strip() for url in self.urls):
            raise ValueError("Compatibility rule sources require non-empty URLs")


@dataclasses.dataclass(frozen=True)
class ToolRequestCompatibilityRule:
    """One versioned provider-request tool declaration limit."""

    rule_id: str
    registry_version: int
    provider: LLMProvider
    adapter: str
    native_format: str
    maximum_declarations: int
    counting_scope: ToolDeclarationCountingScope
    source: ToolCompatibilityRuleSource
    model_developer: LLMModelDeveloper | None = None
    exact_model_identifier: str | None = None
    model_family: str | None = None

    def __post_init__(self) -> None:
        """Normalize and validate one compatibility rule."""
        object.__setattr__(self, "rule_id", _normalize_required(self.rule_id))
        object.__setattr__(self, "adapter", _normalize_required(self.adapter))
        object.__setattr__(
            self,
            "native_format",
            _normalize_required(self.native_format),
        )
        object.__setattr__(
            self,
            "exact_model_identifier",
            _normalize_optional(self.exact_model_identifier),
        )
        object.__setattr__(
            self,
            "model_family",
            _normalize_optional(self.model_family),
        )
        if self.registry_version < 1:
            raise ValueError("Compatibility registry version must be positive")
        if self.maximum_declarations < 1:
            raise ValueError("Maximum tool declarations must be positive")
        if self.exact_model_identifier is not None and self.model_family is not None:
            raise ValueError(
                "Compatibility rules cannot match exact model and family together"
            )

    @property
    def match_kind(self) -> ToolCompatibilityMatchKind:
        """Return deterministic rule specificity."""
        if self.exact_model_identifier is not None:
            return ToolCompatibilityMatchKind.EXACT_MODEL
        if self.model_family is not None:
            return ToolCompatibilityMatchKind.MODEL_FAMILY
        return ToolCompatibilityMatchKind.ENDPOINT

    def matches(self, key: ToolRequestCompatibilityKey) -> bool:
        """Return whether this rule applies to one normalized request key."""
        if (
            self.provider != key.provider
            or self.adapter != key.adapter
            or self.native_format != key.native_format
        ):
            return False
        if (
            self.model_developer is not None
            and self.model_developer != key.model_developer
        ):
            return False
        if self.exact_model_identifier is not None:
            return self.exact_model_identifier == key.model_identifier
        if self.model_family is not None:
            return self.model_family == key.model_family
        return True


@dataclasses.dataclass(frozen=True)
class ProviderHostedToolDeclarationCounts:
    """Provider-hosted declarations by documented counting semantics."""

    total_tools: int
    function_declarations: int

    def __post_init__(self) -> None:
        """Reject negative provider-hosted declaration counts."""
        if self.total_tools < 0 or self.function_declarations < 0:
            raise ValueError("Provider-hosted declaration counts cannot be negative")
        if self.function_declarations > self.total_tools:
            raise ValueError(
                "Function declarations cannot exceed total hosted declarations"
            )

    def counted_by(self, scope: ToolDeclarationCountingScope) -> int:
        """Return declarations that share the supplied provider limit."""
        match scope:
            case ToolDeclarationCountingScope.TOTAL_TOOLS:
                return self.total_tools
            case ToolDeclarationCountingScope.FUNCTION_DECLARATIONS:
                return self.function_declarations
            case _ as unreachable:
                assert_never(unreachable)


@dataclasses.dataclass(frozen=True)
class ResolvedToolDeclarationBudget:
    """Resolved client-function capacity for one prepared provider request."""

    rule: ToolRequestCompatibilityRule | None
    counted_provider_hosted_declarations: int
    client_function_capacity: int | None

    @property
    def maximum_declarations(self) -> int | None:
        """Return the matched hard limit, or None when unlimited."""
        if self.rule is None:
            return None
        return self.rule.maximum_declarations


class ToolRequestCompatibilityConflictError(ValueError):
    """Raised when equally specific compatibility rules can match one request."""


class ToolDeclarationBudgetExceededError(ValueError):
    """Raised before provider I/O when pinned declarations exceed a hard limit."""

    def __init__(
        self,
        *,
        rule_id: str,
        maximum_declarations: int,
        counted_provider_hosted_declarations: int,
        pinned_direct_function_declarations: int,
    ) -> None:
        self.rule_id = rule_id
        self.maximum_declarations = maximum_declarations
        self.counted_provider_hosted_declarations = counted_provider_hosted_declarations
        self.pinned_direct_function_declarations = pinned_direct_function_declarations
        super().__init__(
            "Pinned tool declarations exceed the provider request limit "
            f"for compatibility rule {rule_id}: maximum={maximum_declarations}, "
            f"provider_hosted={counted_provider_hosted_declarations}, "
            f"direct_functions={pinned_direct_function_declarations}"
        )


class ToolRequestCompatibilityRegistry:
    """Resolve verified tool declaration rules by deterministic specificity."""

    def __init__(
        self,
        *,
        version: int,
        rules: Sequence[ToolRequestCompatibilityRule],
    ) -> None:
        if version < 1:
            raise ValueError("Compatibility registry version must be positive")
        self.version = version
        self.rules = tuple(rules)
        for rule in self.rules:
            if rule.registry_version != version:
                raise ValueError(
                    "Compatibility rule version must match registry version"
                )
        _validate_no_same_specificity_overlap(self.rules)

    def resolve(
        self,
        key: ToolRequestCompatibilityKey,
    ) -> ToolRequestCompatibilityRule | None:
        """Return the highest-specificity rule matching one request path."""
        matching = [rule for rule in self.rules if rule.matches(key)]
        if not matching:
            return None
        highest = max(rule.match_kind for rule in matching)
        selected = [rule for rule in matching if rule.match_kind == highest]
        if len(selected) != 1:
            rule_ids = ", ".join(sorted(rule.rule_id for rule in selected))
            raise ToolRequestCompatibilityConflictError(
                "Multiple compatibility rules matched at the same specificity: "
                f"{rule_ids}"
            )
        return selected[0]


def resolve_tool_declaration_budget(
    *,
    registry: ToolRequestCompatibilityRegistry,
    key: ToolRequestCompatibilityKey,
    provider_hosted: ProviderHostedToolDeclarationCounts,
) -> ResolvedToolDeclarationBudget:
    """Resolve the client function capacity for one provider request."""
    rule = registry.resolve(key)
    if rule is None:
        return ResolvedToolDeclarationBudget(
            rule=None,
            counted_provider_hosted_declarations=0,
            client_function_capacity=None,
        )
    counted_provider_hosted = provider_hosted.counted_by(rule.counting_scope)
    return ResolvedToolDeclarationBudget(
        rule=rule,
        counted_provider_hosted_declarations=counted_provider_hosted,
        client_function_capacity=max(
            0,
            rule.maximum_declarations - counted_provider_hosted,
        ),
    )


def ensure_pinned_direct_tools_fit(
    *,
    budget: ResolvedToolDeclarationBudget,
    pinned_direct_function_declarations: int,
) -> None:
    """Fail when provider-hosted and pinned direct declarations exceed a limit."""
    if pinned_direct_function_declarations < 0:
        raise ValueError("Pinned direct declaration count cannot be negative")
    if budget.rule is None or budget.client_function_capacity is None:
        return
    if pinned_direct_function_declarations <= budget.client_function_capacity:
        return
    raise ToolDeclarationBudgetExceededError(
        rule_id=budget.rule.rule_id,
        maximum_declarations=budget.rule.maximum_declarations,
        counted_provider_hosted_declarations=(
            budget.counted_provider_hosted_declarations
        ),
        pinned_direct_function_declarations=pinned_direct_function_declarations,
    )


def build_default_tool_request_compatibility_registry() -> (
    ToolRequestCompatibilityRegistry
):
    """Build the reviewed provider-request compatibility registry."""
    version = 1
    xai_source = ToolCompatibilityRuleSource(
        urls=("https://docs.x.ai/developers/tools/function-calling",),
        verified_on=datetime.date(2026, 7, 19),
        note="xAI documents a maximum of 200 tools per request.",
    )
    vertex_source = ToolCompatibilityRuleSource(
        urls=(
            "https://cloud.google.com/vertex-ai/generative-ai/docs/reference/"
            "rpc/google.cloud.aiplatform.v1#tool",
            "https://cloud.google.com/vertex-ai/generative-ai/docs/"
            "multimodal/function-calling",
        ),
        verified_on=datetime.date(2026, 7, 19),
        note=(
            "Official Vertex AI references conflict at 128 and 512 function "
            "declarations; Azents uses the conservative 128 ceiling."
        ),
    )
    return ToolRequestCompatibilityRegistry(
        version=version,
        rules=(
            ToolRequestCompatibilityRule(
                rule_id="xai-responses-total-tools-200",
                registry_version=version,
                provider=LLMProvider.XAI,
                adapter="litellm",
                native_format="responses",
                maximum_declarations=200,
                counting_scope=ToolDeclarationCountingScope.TOTAL_TOOLS,
                source=xai_source,
            ),
            ToolRequestCompatibilityRule(
                rule_id="xai-oauth-responses-total-tools-200",
                registry_version=version,
                provider=LLMProvider.XAI_OAUTH,
                adapter="litellm",
                native_format="responses",
                maximum_declarations=200,
                counting_scope=ToolDeclarationCountingScope.TOTAL_TOOLS,
                source=xai_source,
            ),
            ToolRequestCompatibilityRule(
                rule_id="vertex-google-responses-functions-128",
                registry_version=version,
                provider=LLMProvider.GOOGLE_VERTEX_AI,
                adapter="litellm",
                native_format="responses",
                model_developer=LLMModelDeveloper.GOOGLE,
                maximum_declarations=128,
                counting_scope=(ToolDeclarationCountingScope.FUNCTION_DECLARATIONS),
                source=vertex_source,
            ),
        ),
    )


def _validate_no_same_specificity_overlap(
    rules: Sequence[ToolRequestCompatibilityRule],
) -> None:
    """Reject rule pairs that can match at the same specificity."""
    seen_rule_ids: set[str] = set()
    for index, rule in enumerate(rules):
        if rule.rule_id in seen_rule_ids:
            raise ToolRequestCompatibilityConflictError(
                f"Duplicate compatibility rule ID: {rule.rule_id}"
            )
        seen_rule_ids.add(rule.rule_id)
        for other in rules[index + 1 :]:
            if _rules_overlap_at_same_specificity(rule, other):
                raise ToolRequestCompatibilityConflictError(
                    "Compatibility rules overlap at the same specificity: "
                    f"{rule.rule_id}, {other.rule_id}"
                )


def _rules_overlap_at_same_specificity(
    left: ToolRequestCompatibilityRule,
    right: ToolRequestCompatibilityRule,
) -> bool:
    """Return whether two equally specific selectors can match one key."""
    if left.match_kind != right.match_kind:
        return False
    if (
        left.provider != right.provider
        or left.adapter != right.adapter
        or left.native_format != right.native_format
    ):
        return False
    if (
        left.model_developer is not None
        and right.model_developer is not None
        and left.model_developer != right.model_developer
    ):
        return False
    match left.match_kind:
        case ToolCompatibilityMatchKind.EXACT_MODEL:
            return left.exact_model_identifier == right.exact_model_identifier
        case ToolCompatibilityMatchKind.MODEL_FAMILY:
            return left.model_family == right.model_family
        case ToolCompatibilityMatchKind.ENDPOINT:
            return True
        case _ as unreachable:
            assert_never(unreachable)


def _normalize_required(value: str) -> str:
    """Normalize one required compatibility identity string."""
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("Compatibility identity values cannot be empty")
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    """Normalize one optional compatibility identity string."""
    if value is None:
        return None
    return _normalize_required(value)
