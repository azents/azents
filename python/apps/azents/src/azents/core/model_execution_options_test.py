"""Model execution option registry tests."""

import pytest
from pydantic import ValidationError

from azents.core.agent import AgentModelSelection
from azents.core.enums import LLMProvider
from azents.core.model_execution_options import (
    ModelExecutionOptionDefinition,
    ModelExecutionOptionId,
    list_model_execution_option_definitions,
    validate_execution_options,
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
            }
        )


def test_list_definitions_without_provider_lists_all_known_definitions() -> None:
    """Allow provider omission only for the complete registry listing."""
    definitions = list_model_execution_option_definitions()

    assert [definition.id for definition in definitions] == [
        ModelExecutionOptionId.FAST
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
