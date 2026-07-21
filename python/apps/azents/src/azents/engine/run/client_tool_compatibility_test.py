"""Tests for model and adapter client tool compatibility profiles."""

import pytest

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.engine.run.client_tool_compatibility import (
    ClientToolAdapterModelProfilePreference,
    ClientToolAdapterProfile,
    ClientToolAdapterProfileConflictError,
    ClientToolAdapterProfileRegistry,
    ClientToolModelCompatibilityConflictError,
    ClientToolModelCompatibilityKey,
    ClientToolModelCompatibilityRegistry,
    ClientToolModelCompatibilityRule,
    ClientToolModelProfile,
    ClientToolRoute,
    resolve_client_tool_adapter_profile,
    resolve_client_tool_model_profiles,
)

_PROFILE = ClientToolModelProfile.V4A_PATCH


def _rule(
    rule_id: str,
    *,
    enabled: bool,
    exact_model_identifier: str | None = None,
    model_family_root: str | None = None,
    model_developer: LLMModelDeveloper = LLMModelDeveloper.OPENAI,
) -> ClientToolModelCompatibilityRule:
    return ClientToolModelCompatibilityRule(
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
) -> ClientToolModelCompatibilityKey:
    return ClientToolModelCompatibilityKey(
        model_identifier=model_identifier,
        model_developer=model_developer,
        model_family=model_family,
    )


def _route(
    *,
    provider: LLMProvider = LLMProvider.OPENAI,
    adapter: str = "openai",
    native_format: str = "responses",
) -> ClientToolRoute:
    return ClientToolRoute(
        provider=provider,
        adapter=adapter,
        native_format=native_format,
    )


def _adapter_profile(
    profile_id: str,
    *,
    provider: LLMProvider | None,
    adapter: str = "test",
) -> ClientToolAdapterProfile:
    return ClientToolAdapterProfile(
        profile_id=profile_id,
        provider=provider,
        adapter=adapter,
        native_format="responses",
        default_wire_dialects=("json_function",),
        model_profile_preferences=(),
    )


def test_default_model_registry_grants_openai_gpt_family() -> None:
    profiles = resolve_client_tool_model_profiles(
        model_identifier="gpt-5.2",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
    )

    assert profiles == frozenset({_PROFILE})


def test_default_model_registry_excludes_non_gpt_and_non_openai_models() -> None:
    assert (
        resolve_client_tool_model_profiles(
            model_identifier="o4-mini",
            model_developer=LLMModelDeveloper.OPENAI,
            model_family="o4",
        )
        == frozenset()
    )
    assert (
        resolve_client_tool_model_profiles(
            model_identifier="gpt-compatible-hosted-model",
            model_developer=LLMModelDeveloper.ANTHROPIC,
            model_family="gpt-5",
        )
        == frozenset()
    )


def test_native_openai_profile_prefers_plaintext_for_v4a_profile() -> None:
    profile = resolve_client_tool_adapter_profile(route=_route())

    assert profile is not None
    assert profile.profile_id == "native-openai-responses"
    assert profile.wire_dialects_for(None) == ("json_function",)
    assert profile.wire_dialects_for(_PROFILE) == (
        "plaintext_custom",
        "json_function",
    )
    assert profile.supports_wire_dialect("plaintext_custom")


def test_native_chatgpt_oauth_uses_the_same_openai_adapter_profile() -> None:
    profile = resolve_client_tool_adapter_profile(
        route=_route(provider=LLMProvider.CHATGPT_OAUTH)
    )

    assert profile is not None
    assert profile.profile_id == "native-openai-responses"
    assert profile.wire_dialects_for(_PROFILE)[0] == "plaintext_custom"


def test_openrouter_profile_overrides_generic_litellm_profile() -> None:
    profile = resolve_client_tool_adapter_profile(
        route=_route(provider=LLMProvider.OPENROUTER, adapter="litellm")
    )

    assert profile is not None
    assert profile.profile_id == "openrouter-litellm-responses"
    assert profile.wire_dialects_for(None) == ("json_function",)
    assert profile.wire_dialects_for(_PROFILE) == ("json_function",)
    assert not profile.supports_wire_dialect("plaintext_custom")


def test_generic_litellm_profile_keeps_ordinary_json_tools_only() -> None:
    profile = resolve_client_tool_adapter_profile(
        route=_route(provider=LLMProvider.OPENAI, adapter="litellm")
    )

    assert profile is not None
    assert profile.profile_id == "generic-litellm-responses"
    assert profile.wire_dialects_for(None) == ("json_function",)
    assert profile.wire_dialects_for(_PROFILE) == ()


def test_unverified_adapter_route_has_no_profile() -> None:
    profile = resolve_client_tool_adapter_profile(
        route=_route(adapter="unverified", native_format="chat")
    )

    assert profile is None


def test_model_registry_normalizes_model_identity() -> None:
    registry = ClientToolModelCompatibilityRegistry(
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
    registry = ClientToolModelCompatibilityRegistry(
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


def test_model_registry_rejects_same_specificity_family_overlap() -> None:
    with pytest.raises(
        ClientToolModelCompatibilityConflictError,
        match="overlap at the same specificity",
    ):
        ClientToolModelCompatibilityRegistry(
            (
                _rule("gpt-family", enabled=True, model_family_root="gpt"),
                _rule("gpt-5-family", enabled=False, model_family_root="gpt-5"),
            )
        )


def test_adapter_registry_rejects_same_specificity_route_overlap() -> None:
    with pytest.raises(
        ClientToolAdapterProfileConflictError,
        match="overlap at the same specificity",
    ):
        ClientToolAdapterProfileRegistry(
            (
                _adapter_profile("first", provider=None),
                _adapter_profile("second", provider=None),
            )
        )


def test_adapter_profile_rejects_duplicate_model_preferences() -> None:
    preference = ClientToolAdapterModelProfilePreference(
        model_profile=_PROFILE,
        wire_dialects=("json_function",),
    )

    with pytest.raises(ValueError, match="cannot repeat a model profile"):
        ClientToolAdapterProfile(
            profile_id="duplicate-model-profile",
            provider=None,
            adapter="test",
            native_format="responses",
            default_wire_dialects=("json_function",),
            model_profile_preferences=(preference, preference),
        )
