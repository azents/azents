"""Selectable model option normalization tests."""

from azcommon.result import Failure, Success

from azents.core.agent import (
    AgentModelSelection,
    AgentModelSelectionInput,
    SelectableModelOptionInput,
)
from azents.services.model_options import normalize_selectable_model_options
from azents.testing.model_selection import make_test_model_selection


async def _resolve_option(
    option_input: SelectableModelOptionInput,
) -> Success[AgentModelSelection]:
    """Return a deterministic model snapshot for a selectable option input."""
    return Success(
        make_test_model_selection(
            integration_id=option_input.model_selection.llm_provider_integration_id,
            model_identifier=option_input.model_selection.model_identifier,
        )
    )


def _option(label: str, model_identifier: str) -> SelectableModelOptionInput:
    """Create a selectable model option input."""
    return SelectableModelOptionInput(
        label=label,
        model_selection=AgentModelSelectionInput(
            llm_provider_integration_id="integration-1",
            model_identifier=model_identifier,
        ),
    )


class TestNormalizeSelectableModelOptions:
    """Selectable model option normalization tests."""

    async def test_rejects_empty_options(self) -> None:
        """At least one option is required."""
        result = await normalize_selectable_model_options(
            option_inputs=[],
            main_model_label=None,
            lightweight_model_label=None,
            resolve_model_selection=_resolve_option,
        )

        assert isinstance(result, Failure)
        assert result.error == ["At least one selectable model is required."]

    async def test_rejects_duplicate_trimmed_labels(self) -> None:
        """Duplicate labels are rejected after trimming whitespace."""
        result = await normalize_selectable_model_options(
            option_inputs=[
                _option("default", "gpt-4o"),
                _option(" default ", "gpt-4o-mini"),
            ],
            main_model_label=None,
            lightweight_model_label=None,
            resolve_model_selection=_resolve_option,
        )

        assert isinstance(result, Failure)
        assert result.error == ["Selectable model labels must be unique."]

    async def test_missing_selected_labels_fall_back_to_first_option(self) -> None:
        """Missing selected labels normalize to the first ordered option."""
        result = await normalize_selectable_model_options(
            option_inputs=[_option(" main ", "gpt-4o"), _option("fast", "gpt-4o-mini")],
            main_model_label="deleted",
            lightweight_model_label="fast",
            resolve_model_selection=_resolve_option,
        )

        assert isinstance(result, Success)
        assert result.value.main_model_label == "main"
        assert result.value.lightweight_model_label == "fast"
        assert result.value.model_selection.model_identifier == "gpt-4o"
        assert (
            result.value.lightweight_model_selection.model_identifier == "gpt-4o-mini"
        )
