"""Tests for model-specific client tool compatibility profiles."""

import pytest

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.engine.run.client_tool_compatibility import (
    ClientToolCompatibilityConflictError,
    ClientToolCompatibilityKey,
    ClientToolCompatibilityRegistry,
    ClientToolCompatibilityRule,
    ClientToolProfile,
    ClientToolRoute,
    resolve_client_tool_profiles,
)

_PROFILE = ClientToolProfile.V4A_APPLY_PATCH_FUNCTION


def _rule(
    rule_id: str,
    *,
    enabled: bool,
    exact_model_identifier: str | None = None,
    model_family_root: str | None = None,
    model_developer: LLMModelDeveloper = LLMModelDeveloper.OPENAI,
) -> ClientToolCompatibilityRule:
    return ClientToolCompatibilityRule(
        rule_id=rule_id,
        profile=_PROFILE,
        model_developer=model_developer,
        enabled=enabled,
        exact_model_identifier=exact_model_identifier,
        model_family_root=model_family_root,
    )


def _key(
    *,
    model_identifier: str = "gpt-5.1",
    model_developer: LLMModelDeveloper | None = LLMModelDeveloper.OPENAI,
    model_family: str | None = "gpt-5",
) -> ClientToolCompatibilityKey:
    return ClientToolCompatibilityKey(
        model_identifier=model_identifier,
        model_developer=model_developer,
        model_family=model_family,
    )


def _route(
    *,
    provider: LLMProvider = LLMProvider.OPENAI,
    adapter: str = "openai",
    native_format: str = "responses",
    official_openai_endpoint: bool = True,
    api_key_available: bool = True,
    custom_rollout_percent: int = 0,
) -> ClientToolRoute:
    return ClientToolRoute(
        provider=provider,
        adapter=adapter,
        native_format=native_format,
        official_openai_endpoint=official_openai_endpoint,
        api_key_available=api_key_available,
        custom_rollout_percent=custom_rollout_percent,
        cohort_key="session-1",
    )


def test_default_registry_grants_openai_gpt_family() -> None:
    profiles = resolve_client_tool_profiles(
        model_identifier="gpt-5.1",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
        route=_route(),
    )

    assert profiles == frozenset({_PROFILE})


def test_default_registry_excludes_non_gpt_and_non_openai_models() -> None:
    assert (
        resolve_client_tool_profiles(
            model_identifier="o4-mini",
            model_developer=LLMModelDeveloper.OPENAI,
            model_family="o4",
            route=_route(),
        )
        == frozenset()
    )
    assert (
        resolve_client_tool_profiles(
            model_identifier="gpt-compatible-hosted-model",
            model_developer=LLMModelDeveloper.ANTHROPIC,
            model_family="gpt-5",
            route=_route(),
        )
        == frozenset()
    )


def test_exact_official_openai_route_selects_custom_only_when_enabled() -> None:
    custom_profiles = resolve_client_tool_profiles(
        model_identifier="gpt-5.1",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
        route=_route(custom_rollout_percent=100),
    )
    fallback_profiles = resolve_client_tool_profiles(
        model_identifier="gpt-5.1",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
        route=_route(custom_rollout_percent=0),
    )

    assert custom_profiles == frozenset(
        {ClientToolProfile.V4A_APPLY_PATCH_PLAINTEXT_CUSTOM}
    )
    assert fallback_profiles == frozenset({_PROFILE})


def test_custom_route_denial_retains_only_verified_function_fallback() -> None:
    custom_base_url = resolve_client_tool_profiles(
        model_identifier="gpt-5.1",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
        route=_route(
            official_openai_endpoint=False,
            custom_rollout_percent=100,
        ),
    )
    openrouter = resolve_client_tool_profiles(
        model_identifier="gpt-5.1",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
        route=_route(
            provider=LLMProvider.OPENROUTER,
            adapter="litellm",
            official_openai_endpoint=False,
            api_key_available=False,
            custom_rollout_percent=100,
        ),
    )

    assert custom_base_url == frozenset({_PROFILE})
    assert openrouter == frozenset({_PROFILE})


def test_unverified_route_omits_apply_patch_instead_of_falling_back() -> None:
    profiles = resolve_client_tool_profiles(
        model_identifier="gpt-5.1",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
        route=_route(adapter="unverified", native_format="chat"),
    )

    assert profiles == frozenset()


def test_partial_rollout_cohort_selection_is_stable() -> None:
    route = _route(custom_rollout_percent=50)

    first = resolve_client_tool_profiles(
        model_identifier="gpt-5.1",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
        route=route,
    )
    second = resolve_client_tool_profiles(
        model_identifier="gpt-5.1",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
        route=route,
    )

    assert first == second
    assert first in {
        frozenset({_PROFILE}),
        frozenset({ClientToolProfile.V4A_APPLY_PATCH_PLAINTEXT_CUSTOM}),
    }


def test_registry_normalizes_model_identity() -> None:
    registry = ClientToolCompatibilityRegistry(
        (
            _rule(
                "normalized-family",
                enabled=True,
                model_family_root=" GPT ",
            ),
        )
    )

    profiles = registry.resolve(
        _key(
            model_identifier=" GPT-5.1 ",
            model_family=" GPT-5 ",
        )
    )

    assert profiles == frozenset({_PROFILE})


def test_exact_model_deny_overrides_family_grant() -> None:
    registry = ClientToolCompatibilityRegistry(
        (
            _rule("gpt-family", enabled=True, model_family_root="gpt"),
            _rule(
                "incompatible-release",
                enabled=False,
                exact_model_identifier="gpt-5.1",
            ),
        )
    )

    assert registry.resolve(_key()) == frozenset()
    assert registry.resolve(_key(model_identifier="gpt-5.2")) == frozenset({_PROFILE})


def test_registry_rejects_same_specificity_family_overlap() -> None:
    with pytest.raises(
        ClientToolCompatibilityConflictError,
        match="overlap at the same specificity",
    ):
        ClientToolCompatibilityRegistry(
            (
                _rule("gpt-family", enabled=True, model_family_root="gpt"),
                _rule("gpt-5-family", enabled=False, model_family_root="gpt-5"),
            )
        )
