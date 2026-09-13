"""Selectable model option normalization tests."""

from azcommon.result import Failure, Success

from azents.core.agent import (
    AgentModelSelection,
    AgentModelSelectionInput,
    BuiltinToolConfig,
    SelectableModelCandidateInput,
    SelectableModelOptionInput,
    SelectableModelSettings,
    SelectableModelSettingsInput,
)
from azents.services.model_options import normalize_selectable_model_options
from azents.testing.model_selection import make_test_model_selection


async def _resolve_candidate(
    candidate_input: SelectableModelCandidateInput,
) -> Success[AgentModelSelection]:
    """Return a deterministic model snapshot for a candidate input."""
    selection = make_test_model_selection(
        integration_id=candidate_input.model_selection.llm_provider_integration_id,
        model_identifier=candidate_input.model_selection.model_identifier,
    )
    if "search" in selection.model_identifier:
        selection.normalized_capabilities.built_in_tools.supported = ["web_search"]
    return Success(selection)


async def _validate_image_generation_config(
    selection: AgentModelSelection,
    settings: SelectableModelSettings,
) -> list[str]:
    """Accept image-generation settings in general normalization tests."""
    del selection, settings
    return []


def _candidate(
    model_identifier: str,
    *,
    integration_id: str = "integration-1",
) -> SelectableModelCandidateInput:
    """Create one physical candidate input."""
    return SelectableModelCandidateInput(
        model_selection=AgentModelSelectionInput(
            llm_provider_integration_id=integration_id,
            model_identifier=model_identifier,
        )
    )


def _option(label: str, model_identifier: str) -> SelectableModelOptionInput:
    """Create a selectable model option input."""
    return SelectableModelOptionInput(
        label=label,
        candidates=[_candidate(model_identifier)],
    )


class TestNormalizeSelectableModelOptions:
    """Selectable model option normalization tests."""

    async def test_rejects_empty_options(self) -> None:
        """At least one option is required."""
        result = await normalize_selectable_model_options(
            option_inputs=[],
            main_model_label=None,
            lightweight_model_label=None,
            resolve_model_selection=_resolve_candidate,
            validate_image_generation_config=_validate_image_generation_config,
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
            resolve_model_selection=_resolve_candidate,
            validate_image_generation_config=_validate_image_generation_config,
        )

        assert isinstance(result, Failure)
        assert result.error == ["Selectable model labels must be unique."]

    async def test_missing_selected_labels_fall_back_to_first_option(self) -> None:
        """Missing selected labels normalize to the first ordered option."""
        result = await normalize_selectable_model_options(
            option_inputs=[_option(" main ", "gpt-4o"), _option("fast", "mini")],
            main_model_label="deleted",
            lightweight_model_label="fast",
            resolve_model_selection=_resolve_candidate,
            validate_image_generation_config=_validate_image_generation_config,
        )

        assert isinstance(result, Success)
        assert result.value.main_model_label == "main"
        assert result.value.lightweight_model_label == "fast"
        assert result.value.model_selection.model_identifier == "gpt-4o"
        assert result.value.lightweight_model_selection.model_identifier == "mini"

    async def test_resolves_ordered_candidates_and_primary_mirror(self) -> None:
        """Every candidate is resolved and the first remains the Primary mirror."""
        option = _option("default", "primary")
        option.candidates.append(_candidate("fallback", integration_id="integration-2"))

        result = await normalize_selectable_model_options(
            option_inputs=[option],
            main_model_label="default",
            lightweight_model_label="default",
            resolve_model_selection=_resolve_candidate,
            validate_image_generation_config=_validate_image_generation_config,
        )

        assert isinstance(result, Success)
        stored = result.value.selectable_model_options[0]
        assert [
            candidate.model_selection.model_identifier
            for candidate in stored.candidates
        ] == ["primary", "fallback"]
        assert result.value.model_selection.model_identifier == "primary"
        assert result.value.lightweight_model_selection.model_identifier == "primary"

    async def test_rejects_duplicate_candidate_identity_within_label(self) -> None:
        """One label cannot contain the same physical candidate twice."""
        option = _option("default", "gpt-4o")
        option.candidates.append(option.candidates[0].model_copy(deep=True))

        result = await normalize_selectable_model_options(
            option_inputs=[option],
            main_model_label=None,
            lightweight_model_label=None,
            resolve_model_selection=_resolve_candidate,
            validate_image_generation_config=_validate_image_generation_config,
        )

        assert isinstance(result, Failure)
        assert result.error == [
            "Selectable model 'default' candidate identities must be unique."
        ]

    async def test_omitted_settings_enable_supported_implemented_tools(self) -> None:
        """Capability-derived defaults enable every implemented supported tool."""
        result = await normalize_selectable_model_options(
            option_inputs=[_option("research", "search-model")],
            main_model_label=None,
            lightweight_model_label=None,
            resolve_model_selection=_resolve_candidate,
            validate_image_generation_config=_validate_image_generation_config,
        )

        assert isinstance(result, Success)
        stored = result.value.selectable_model_options[0]
        settings = stored.candidates[0].settings
        assert settings.context_window_tokens is None
        assert settings.max_output_tokens is None
        assert [tool.name for tool in settings.builtin_tools] == ["web_search"]
        assert stored.subagent_enabled is True
        assert stored.subagent_guidance is None

    async def test_explicit_empty_tools_preserve_all_off_intent(self) -> None:
        """An explicit empty tool list remains distinct from omitted defaults."""
        option = _option("research", "search-model")
        option.candidates[0].settings = SelectableModelSettingsInput(
            context_window_tokens=32_000,
            max_output_tokens=4_000,
            builtin_tools=[],
        )

        result = await normalize_selectable_model_options(
            option_inputs=[option],
            main_model_label=None,
            lightweight_model_label=None,
            resolve_model_selection=_resolve_candidate,
            validate_image_generation_config=_validate_image_generation_config,
        )

        assert isinstance(result, Success)
        settings = result.value.selectable_model_options[0].candidates[0].settings
        assert settings.context_window_tokens == 32_000
        assert settings.max_output_tokens == 4_000
        assert settings.builtin_tools == []

    async def test_normalizes_subagent_policy(self) -> None:
        """Subagent policy preserves availability and trims optional guidance."""
        option = _option("research", "plain-model")
        option.subagent_enabled = False
        option.subagent_guidance = "  Prefer only for bounded research.  "

        result = await normalize_selectable_model_options(
            option_inputs=[option],
            main_model_label=None,
            lightweight_model_label=None,
            resolve_model_selection=_resolve_candidate,
            validate_image_generation_config=_validate_image_generation_config,
        )

        assert isinstance(result, Success)
        stored = result.value.selectable_model_options[0]
        assert stored.subagent_enabled is False
        assert stored.subagent_guidance == "Prefer only for bounded research."

    async def test_normalizes_blank_subagent_guidance_to_null(self) -> None:
        """Whitespace-only subagent guidance is stored as null."""
        option = _option("research", "plain-model")
        option.subagent_guidance = "  \n  "

        result = await normalize_selectable_model_options(
            option_inputs=[option],
            main_model_label=None,
            lightweight_model_label=None,
            resolve_model_selection=_resolve_candidate,
            validate_image_generation_config=_validate_image_generation_config,
        )

        assert isinstance(result, Success)
        assert result.value.selectable_model_options[0].subagent_guidance is None

    async def test_omitted_tool_list_uses_capability_defaults(self) -> None:
        """Explicit token settings may still request default built-in tools."""
        option = _option("research", "search-model")
        option.candidates[0].settings = SelectableModelSettingsInput(
            context_window_tokens=16_000,
            max_output_tokens=None,
            builtin_tools=None,
        )

        result = await normalize_selectable_model_options(
            option_inputs=[option],
            main_model_label=None,
            lightweight_model_label=None,
            resolve_model_selection=_resolve_candidate,
            validate_image_generation_config=_validate_image_generation_config,
        )

        assert isinstance(result, Success)
        settings = result.value.selectable_model_options[0].candidates[0].settings
        assert settings.context_window_tokens == 16_000
        assert [tool.name for tool in settings.builtin_tools] == ["web_search"]

    async def test_rejects_unsupported_and_duplicate_tools_per_candidate(self) -> None:
        """Invalid built-in tool intent is reported against its candidate."""
        option = _option("plain", "plain-model")
        option.candidates[0].settings = SelectableModelSettingsInput(
            context_window_tokens=None,
            max_output_tokens=None,
            builtin_tools=[
                BuiltinToolConfig(name="web_search"),
                BuiltinToolConfig(name="web_search"),
            ],
        )

        result = await normalize_selectable_model_options(
            option_inputs=[option],
            main_model_label=None,
            lightweight_model_label=None,
            resolve_model_selection=_resolve_candidate,
            validate_image_generation_config=_validate_image_generation_config,
        )

        assert isinstance(result, Failure)
        assert result.error == [
            "Selectable model 'plain' candidate 1: Built-in tool names must be unique.",
            (
                "Selectable model 'plain' candidate 1: Model 'plain-model' does "
                "not support Web Search."
            ),
        ]
