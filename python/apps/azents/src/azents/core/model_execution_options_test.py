"""Model execution option registry tests."""

import pytest
from pydantic import ValidationError

from azents.core.agent import AgentModelSelection
from azents.core.enums import LLMProvider
from azents.core.model_execution_options import (
    MODEL_EXECUTION_OPTION_DEFINITIONS,
    ModelExecutionOptionDefinition,
    ModelExecutionOptionId,
    list_model_execution_option_definitions,
    validate_enabled_execution_options,
    validate_execution_options,
    validate_supported_execution_options,
)


def test_execution_option_control_is_required() -> None:
    """Require new option definitions to declare their control type explicitly."""
    with pytest.raises(ValidationError):
        ModelExecutionOptionDefinition.model_validate(
            {
                "id": ModelExecutionOptionId.FAST,
                "label": "Fast",
                "description": "Request faster processing.",
                "cost_hint": "Additional cost may apply.",
                "exclusive_group": "processing_speed",
            }
        )


def test_list_definitions_without_provider_lists_all_known_definitions() -> None:
    """Allow provider omission only for the complete registry listing."""
    definitions = list_model_execution_option_definitions()

    assert [definition.id for definition in definitions] == [
        ModelExecutionOptionId.FAST,
        ModelExecutionOptionId.ULTRAFAST,
    ]


def test_list_definitions_requires_provider_when_filtering() -> None:
    """Require a concrete provider for a filtered descriptor projection."""
    with pytest.raises(ValueError, match="Provider is required"):
        list_model_execution_option_definitions(supported=[ModelExecutionOptionId.FAST])


def test_fast_definition_has_stable_public_contract() -> None:
    """Expose only the bounded boolean Fast definition metadata."""
    definitions = list_model_execution_option_definitions(
        provider=LLMProvider.OPENAI,
        supported=[ModelExecutionOptionId.FAST],
    )

    assert [definition.id for definition in definitions] == [
        ModelExecutionOptionId.FAST
    ]
    assert definitions[0].control == "boolean"
    assert definitions[0].exclusive_group == "processing_speed"
    assert definitions[0].cost_hint == "Additional OpenAI API cost may apply."


def test_chatgpt_fast_definition_uses_subscription_cost_hint() -> None:
    """Use ChatGPT-specific usage wording for the public descriptor."""
    definitions = list_model_execution_option_definitions(
        provider=LLMProvider.CHATGPT_OAUTH,
        supported=[ModelExecutionOptionId.FAST],
    )

    assert definitions[0].cost_hint == (
        "Additional ChatGPT usage or credits may apply."
    )


def test_validate_execution_options_canonicalizes_enabled_ids() -> None:
    """Return enabled IDs in canonical registry order."""
    assert validate_execution_options(
        provider=LLMProvider.OPENAI,
        supported=[ModelExecutionOptionId.FAST],
        enabled=[ModelExecutionOptionId.FAST],
    ) == [ModelExecutionOptionId.FAST]


@pytest.mark.parametrize(
    "provider",
    [LLMProvider.ANTHROPIC, LLMProvider.GOOGLE_GEMINI],
)
def test_validate_execution_options_rejects_fast_for_other_providers(
    provider: LLMProvider,
) -> None:
    """Do not admit malformed Fast support for unrelated providers."""
    with pytest.raises(ValueError, match="not supported by this provider"):
        validate_execution_options(
            provider=provider,
            supported=[ModelExecutionOptionId.FAST],
            enabled=[],
        )


def test_validate_execution_options_rejects_unsupported_enabled_id() -> None:
    """Reject an enabled option missing from the saved model support list."""
    with pytest.raises(ValueError, match="not supported by the model"):
        validate_execution_options(
            provider=LLMProvider.OPENAI,
            supported=[],
            enabled=[ModelExecutionOptionId.FAST],
        )


def test_agent_model_selection_defaults_historical_option_support_to_empty() -> None:
    """Allow historical selection snapshots that predate execution options."""
    selection = AgentModelSelection.model_validate(
        {
            "llm_provider_integration_id": "integration-1",
            "provider": "openai",
            "model_identifier": "gpt-5",
            "model_display_name": "GPT-5",
            "model_developer": "openai",
            "normalized_capabilities": {},
            "model_snapshot": {},
        }
    )

    assert selection.supported_execution_options == []


def test_execution_option_exclusive_group_is_required_nullable() -> None:
    """Require explicit grouping without making every option exclusive."""
    payload = {
        "id": "fast",
        "label": "Fast",
        "description": "Request faster processing.",
        "cost_hint": "Additional cost may apply.",
        "control": "boolean",
    }
    with pytest.raises(ValidationError, match="exclusive_group"):
        ModelExecutionOptionDefinition.model_validate(payload)
    definition = ModelExecutionOptionDefinition.model_validate(
        {**payload, "exclusive_group": None}
    )
    assert definition.exclusive_group is None
    assert "exclusive_group" in definition.model_json_schema()["required"]


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH])
def test_support_both_options_is_valid_and_definitions_have_shared_group(
    provider: LLMProvider,
) -> None:
    """Support enumeration permits every mutually exclusive capability."""
    supported = [ModelExecutionOptionId.ULTRAFAST, ModelExecutionOptionId.FAST]
    canonical = [ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST]
    assert (
        validate_supported_execution_options(provider=provider, supported=supported)
        == canonical
    )
    assert (
        validate_execution_options(provider=provider, supported=supported, enabled=[])
        == []
    )
    definitions = list_model_execution_option_definitions(
        provider=provider, supported=supported
    )
    assert [definition.id for definition in definitions] == canonical
    assert all(
        definition.exclusive_group == "processing_speed"
        and definition.control == "boolean"
        for definition in definitions
    )
    hint = (
        "Additional OpenAI API cost may apply."
        if provider == LLMProvider.OPENAI
        else "Additional ChatGPT usage or credits may apply."
    )
    assert definitions[0].cost_hint == hint
    assert definitions[1].cost_hint == (
        f"{hint} Ultrafast cost estimates are unavailable."
    )


@pytest.mark.parametrize(
    "enabled",
    [[], [ModelExecutionOptionId.FAST], [ModelExecutionOptionId.ULTRAFAST]],
)
def test_enabled_preference_shapes_are_valid(
    enabled: list[ModelExecutionOptionId],
) -> None:
    """Preserve Normal, Fast, and Ultrafast in the existing option-list format."""
    assert validate_enabled_execution_options(enabled=enabled) == enabled
    assert (
        validate_execution_options(
            provider=LLMProvider.OPENAI,
            supported=[ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST],
            enabled=enabled,
        )
        == enabled
    )


@pytest.mark.parametrize(
    "enabled",
    [
        [ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST],
        [ModelExecutionOptionId.ULTRAFAST, ModelExecutionOptionId.FAST],
    ],
)
def test_enabled_speed_conflict_fails_independent_of_order(
    enabled: list[ModelExecutionOptionId],
) -> None:
    """Reject conflicting preferences rather than choosing a list member."""
    with pytest.raises(ValueError, match="exclusive"):
        validate_enabled_execution_options(enabled=enabled)
    with pytest.raises(ValueError, match="exclusive"):
        validate_execution_options(
            provider=LLMProvider.OPENAI,
            supported=[ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST],
            enabled=enabled,
        )


@pytest.mark.parametrize("option_id", list(ModelExecutionOptionId))
def test_support_and_enabled_duplicates_fail(option_id: ModelExecutionOptionId) -> None:
    """Reject duplicate IDs in either independently validated collection."""
    with pytest.raises(ValueError, match="Supported.*unique"):
        validate_supported_execution_options(
            provider=LLMProvider.OPENAI, supported=[option_id, option_id]
        )
    with pytest.raises(ValueError, match="Enabled.*unique"):
        validate_enabled_execution_options(enabled=[option_id, option_id])


@pytest.mark.parametrize("option_id", list(ModelExecutionOptionId))
def test_unimplemented_ids_fail_both_shared_validators(
    monkeypatch: pytest.MonkeyPatch,
    option_id: ModelExecutionOptionId,
) -> None:
    """The implemented registry remains authoritative beyond enum decoding."""
    monkeypatch.delitem(MODEL_EXECUTION_OPTION_DEFINITIONS, option_id)
    with pytest.raises(ValueError, match="Unknown supported"):
        validate_supported_execution_options(
            provider=LLMProvider.OPENAI, supported=[option_id]
        )
    with pytest.raises(ValueError, match="Unknown enabled"):
        validate_enabled_execution_options(enabled=[option_id])


@pytest.mark.parametrize(
    "provider",
    [
        provider
        for provider in LLMProvider
        if provider not in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}
    ],
)
@pytest.mark.parametrize("option_id", list(ModelExecutionOptionId))
def test_other_providers_reject_both_premium_capabilities(
    provider: LLMProvider, option_id: ModelExecutionOptionId
) -> None:
    """Do not infer support from API-compatible providers."""
    assert validate_supported_execution_options(provider=provider, supported=[]) == []
    with pytest.raises(ValueError, match="not supported by this provider"):
        validate_supported_execution_options(provider=provider, supported=[option_id])


def test_ultrafast_only_support_does_not_imply_fast() -> None:
    """Preserve independent Ultrafast-only saved support declarations."""
    definitions = list_model_execution_option_definitions(
        provider=LLMProvider.CHATGPT_OAUTH,
        supported=[ModelExecutionOptionId.ULTRAFAST],
    )
    assert [definition.id for definition in definitions] == [
        ModelExecutionOptionId.ULTRAFAST
    ]
    with pytest.raises(ValueError, match="not supported by the model"):
        validate_execution_options(
            provider=LLMProvider.CHATGPT_OAUTH,
            supported=[ModelExecutionOptionId.ULTRAFAST],
            enabled=[ModelExecutionOptionId.FAST],
        )


def test_saved_support_snapshot_is_not_inferred_from_model_id() -> None:
    """Historical Astra selections stay unsupported until explicitly re-saved."""
    payload = {
        "llm_provider_integration_id": "integration-1",
        "provider": "openai",
        "model_identifier": "gpt-6-astra",
        "model_display_name": "GPT-6-Astra",
        "model_developer": "openai",
        "normalized_capabilities": {},
        "model_snapshot": {},
    }
    historical = AgentModelSelection.model_validate(payload)
    assert historical.supported_execution_options == []
    with pytest.raises(ValueError, match="not supported by the model"):
        validate_execution_options(
            provider=historical.provider,
            supported=historical.supported_execution_options,
            enabled=[ModelExecutionOptionId.ULTRAFAST],
        )
    refreshed = AgentModelSelection.model_validate(
        {**payload, "supported_execution_options": ["fast", "ultrafast"]}
    )
    assert refreshed.supported_execution_options == [
        ModelExecutionOptionId.FAST,
        ModelExecutionOptionId.ULTRAFAST,
    ]
    assert validate_execution_options(
        provider=refreshed.provider,
        supported=refreshed.supported_execution_options,
        enabled=[ModelExecutionOptionId.ULTRAFAST],
    ) == [ModelExecutionOptionId.ULTRAFAST]
