"""Tests for provider-request tool declaration compatibility budgets."""

import datetime

import pytest

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.engine.run.tool_budget import (
    ProviderHostedToolDeclarationCounts,
    ToolCompatibilityRuleSource,
    ToolDeclarationBudgetExceededError,
    ToolDeclarationCountingScope,
    ToolRequestCompatibilityConflictError,
    ToolRequestCompatibilityKey,
    ToolRequestCompatibilityRegistry,
    ToolRequestCompatibilityRule,
    build_default_tool_request_compatibility_registry,
    ensure_pinned_direct_tools_fit,
    resolve_tool_declaration_budget,
)

_SOURCE = ToolCompatibilityRuleSource(
    urls=("https://example.com/provider-tool-limit",),
    verified_on=datetime.date(2026, 7, 19),
    note=None,
)


def _rule(
    rule_id: str,
    *,
    exact_model_identifier: str | None = None,
    model_family: str | None = None,
    model_developer: LLMModelDeveloper | None = None,
    maximum_declarations: int = 100,
) -> ToolRequestCompatibilityRule:
    return ToolRequestCompatibilityRule(
        rule_id=rule_id,
        registry_version=1,
        provider=LLMProvider.OPENAI,
        adapter="openai",
        native_format="responses",
        exact_model_identifier=exact_model_identifier,
        model_family=model_family,
        model_developer=model_developer,
        maximum_declarations=maximum_declarations,
        counting_scope=ToolDeclarationCountingScope.TOTAL_TOOLS,
        source=_SOURCE,
    )


def _key(
    *,
    provider: LLMProvider = LLMProvider.OPENAI,
    adapter: str = "openai",
    model_identifier: str = "gpt-5.1",
    model_developer: LLMModelDeveloper | None = LLMModelDeveloper.OPENAI,
    model_family: str | None = "gpt-5",
) -> ToolRequestCompatibilityKey:
    return ToolRequestCompatibilityKey(
        provider=provider,
        adapter=adapter,
        native_format="responses",
        model_identifier=model_identifier,
        model_developer=model_developer,
        model_family=model_family,
    )


def test_registry_resolves_exact_before_family_before_endpoint() -> None:
    registry = ToolRequestCompatibilityRegistry(
        version=1,
        rules=(
            _rule("endpoint", maximum_declarations=100),
            _rule(
                "family",
                model_family="gpt-5",
                maximum_declarations=80,
            ),
            _rule(
                "exact",
                exact_model_identifier="gpt-5.1",
                maximum_declarations=60,
            ),
        ),
    )

    exact = registry.resolve(_key())
    family = registry.resolve(_key(model_identifier="gpt-5.2"))
    endpoint = registry.resolve(_key(model_identifier="o4-mini", model_family="o4"))

    assert exact is not None
    assert exact.rule_id == "exact"
    assert family is not None
    assert family.rule_id == "family"
    assert endpoint is not None
    assert endpoint.rule_id == "endpoint"


def test_registry_normalizes_request_identity() -> None:
    registry = ToolRequestCompatibilityRegistry(
        version=1,
        rules=(
            _rule(
                "exact",
                exact_model_identifier="GPT-5.1",
            ),
        ),
    )

    matched = registry.resolve(
        _key(
            adapter=" OpenAI ",
            model_identifier=" GPT-5.1 ",
            model_family=" GPT-5 ",
        )
    )

    assert matched is not None
    assert matched.rule_id == "exact"


def test_registry_rejects_same_specificity_overlap() -> None:
    with pytest.raises(
        ToolRequestCompatibilityConflictError,
        match="overlap at the same specificity",
    ):
        ToolRequestCompatibilityRegistry(
            version=1,
            rules=(
                _rule("generic-family", model_family="gpt-5"),
                _rule(
                    "developer-family",
                    model_family="gpt-5",
                    model_developer=LLMModelDeveloper.OPENAI,
                ),
            ),
        )


def test_unknown_request_path_remains_unlimited() -> None:
    budget = resolve_tool_declaration_budget(
        registry=build_default_tool_request_compatibility_registry(),
        key=_key(provider=LLMProvider.ANTHROPIC, adapter="litellm"),
        provider_hosted=ProviderHostedToolDeclarationCounts(
            total_tools=2,
            function_declarations=0,
        ),
    )

    assert budget.rule is None
    assert budget.maximum_declarations is None
    assert budget.client_function_capacity is None
    assert budget.counted_provider_hosted_declarations == 0


def test_xai_limit_counts_provider_hosted_tools() -> None:
    budget = resolve_tool_declaration_budget(
        registry=build_default_tool_request_compatibility_registry(),
        key=_key(
            provider=LLMProvider.XAI,
            adapter="litellm",
            model_identifier="grok-4",
            model_developer=LLMModelDeveloper.XAI,
            model_family="grok-4",
        ),
        provider_hosted=ProviderHostedToolDeclarationCounts(
            total_tools=2,
            function_declarations=0,
        ),
    )

    assert budget.rule is not None
    assert budget.rule.rule_id == "xai-responses-total-tools-200"
    assert budget.maximum_declarations == 200
    assert budget.counted_provider_hosted_declarations == 2
    assert budget.client_function_capacity == 198


def test_vertex_google_limit_counts_only_function_declarations() -> None:
    budget = resolve_tool_declaration_budget(
        registry=build_default_tool_request_compatibility_registry(),
        key=_key(
            provider=LLMProvider.GOOGLE_VERTEX_AI,
            adapter="litellm",
            model_identifier="gemini-2.5-pro",
            model_developer=LLMModelDeveloper.GOOGLE,
            model_family="gemini-2.5-pro",
        ),
        provider_hosted=ProviderHostedToolDeclarationCounts(
            total_tools=2,
            function_declarations=0,
        ),
    )

    assert budget.rule is not None
    assert budget.rule.rule_id == "vertex-google-responses-functions-128"
    assert budget.maximum_declarations == 128
    assert budget.counted_provider_hosted_declarations == 0
    assert budget.client_function_capacity == 128


def test_vertex_anthropic_does_not_inherit_google_limit() -> None:
    budget = resolve_tool_declaration_budget(
        registry=build_default_tool_request_compatibility_registry(),
        key=_key(
            provider=LLMProvider.GOOGLE_VERTEX_AI,
            adapter="litellm",
            model_identifier="claude-sonnet-4@20250514",
            model_developer=LLMModelDeveloper.ANTHROPIC,
            model_family="claude-sonnet-4",
        ),
        provider_hosted=ProviderHostedToolDeclarationCounts(
            total_tools=1,
            function_declarations=0,
        ),
    )

    assert budget.rule is None
    assert budget.client_function_capacity is None


def test_direct_gemini_api_remains_unmatched() -> None:
    budget = resolve_tool_declaration_budget(
        registry=build_default_tool_request_compatibility_registry(),
        key=_key(
            provider=LLMProvider.GOOGLE_GEMINI,
            adapter="litellm",
            model_identifier="gemini-2.5-pro",
            model_developer=LLMModelDeveloper.GOOGLE,
            model_family="gemini-2.5-pro",
        ),
        provider_hosted=ProviderHostedToolDeclarationCounts(
            total_tools=1,
            function_declarations=0,
        ),
    )

    assert budget.rule is None
    assert budget.client_function_capacity is None


def test_vertex_rule_records_conflicting_official_sources() -> None:
    registry = build_default_tool_request_compatibility_registry()
    rule = next(
        rule
        for rule in registry.rules
        if rule.rule_id == "vertex-google-responses-functions-128"
    )

    assert rule.source.verified_on == datetime.date(2026, 7, 19)
    assert len(rule.source.urls) == 2
    assert rule.source.note is not None
    assert "128 and 512" in rule.source.note


def test_direct_overflow_raises_typed_preparation_error() -> None:
    budget = resolve_tool_declaration_budget(
        registry=ToolRequestCompatibilityRegistry(
            version=1,
            rules=(_rule("small", maximum_declarations=3),),
        ),
        key=_key(),
        provider_hosted=ProviderHostedToolDeclarationCounts(
            total_tools=1,
            function_declarations=0,
        ),
    )

    with pytest.raises(ToolDeclarationBudgetExceededError) as error:
        ensure_pinned_direct_tools_fit(
            budget=budget,
            pinned_direct_function_declarations=3,
        )

    assert error.value.rule_id == "small"
    assert error.value.maximum_declarations == 3
    assert error.value.counted_provider_hosted_declarations == 1
    assert error.value.pinned_direct_function_declarations == 3
