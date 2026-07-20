"""Tests for model-specific client tool compatibility profiles."""

import pytest

from azents.core.enums import LLMModelDeveloper
from azents.engine.run.client_tool_compatibility import (
    ClientToolCompatibilityConflictError,
    ClientToolCompatibilityKey,
    ClientToolCompatibilityRegistry,
    ClientToolCompatibilityRule,
    ClientToolProfile,
    resolve_client_tool_profiles,
)

_PROFILE = ClientToolProfile.GPT_V4A_APPLY_PATCH


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


def test_default_registry_grants_openai_gpt_family() -> None:
    profiles = resolve_client_tool_profiles(
        model_identifier="gpt-5.1",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
    )

    assert profiles == frozenset({_PROFILE})


def test_default_registry_excludes_non_gpt_and_non_openai_models() -> None:
    assert (
        resolve_client_tool_profiles(
            model_identifier="o4-mini",
            model_developer=LLMModelDeveloper.OPENAI,
            model_family="o4",
        )
        == frozenset()
    )
    assert (
        resolve_client_tool_profiles(
            model_identifier="gpt-compatible-hosted-model",
            model_developer=LLMModelDeveloper.ANTHROPIC,
            model_family="gpt-5",
        )
        == frozenset()
    )


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
