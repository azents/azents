"""Agent model selection fixture for tests."""

from azents.core.agent import (
    DEFAULT_MAIN_MODEL_OPTION_LABEL,
    AgentModelSelection,
    SelectableModelOption,
    SelectableModelSettings,
    default_selectable_model_settings,
)
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities


def make_test_model_selection(
    *,
    integration_id: str = "integ-1",
    provider: LLMProvider = LLMProvider.OPENAI,
    model_identifier: str = "gpt-4o",
    model_developer: LLMModelDeveloper = LLMModelDeveloper.OPENAI,
) -> AgentModelSelection:
    """Create model selection snapshot for tests."""
    return AgentModelSelection(
        llm_provider_integration_id=integration_id,
        provider=provider,
        model_identifier=model_identifier,
        model_display_name=model_identifier,
        model_developer=model_developer,
        model_family=None,
        normalized_capabilities=ModelCapabilities(),
        model_snapshot={"id": model_identifier},
        source_metadata=None,
        last_refreshed_at=None,
    )


def make_test_model_selection_dict(
    *,
    integration_id: str = "integ-1",
    provider: LLMProvider = LLMProvider.OPENAI,
    model_identifier: str = "gpt-4o",
    model_developer: LLMModelDeveloper = LLMModelDeveloper.OPENAI,
) -> dict[str, object]:
    """Create model selection JSONB dict for tests."""
    return make_test_model_selection(
        integration_id=integration_id,
        provider=provider,
        model_identifier=model_identifier,
        model_developer=model_developer,
    ).model_dump(mode="json")


def make_test_model_settings() -> SelectableModelSettings:
    """Create empty model-scoped settings for tests."""
    return SelectableModelSettings(
        context_window_tokens=None,
        max_output_tokens=None,
        builtin_tools=[],
    )


def make_test_selectable_model_options(
    selection: AgentModelSelection,
    *,
    label: str = DEFAULT_MAIN_MODEL_OPTION_LABEL,
) -> list[SelectableModelOption]:
    """Create selectable model options for tests."""
    return [
        SelectableModelOption(
            label=label,
            model_selection=selection,
            settings=default_selectable_model_settings(selection),
        )
    ]
