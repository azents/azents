"""Selectable model option normalization helpers."""

import dataclasses
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from azcommon.result import Failure, Result, Success

from azents.core.agent import (
    MAX_SELECTABLE_MODEL_CANDIDATES,
    MAX_SELECTABLE_MODEL_LABEL_LENGTH,
    MAX_SELECTABLE_MODEL_OPTIONS,
    AgentModelSelection,
    SelectableModelCandidate,
    SelectableModelCandidateInput,
    SelectableModelOption,
    SelectableModelOptionInput,
    SelectableModelSettings,
    SelectableModelSettingsInput,
    default_selectable_model_settings,
)
from azents.core.builtin_tools import (
    BuiltinToolValidationContext,
    validate_builtin_tools,
)
from azents.core.llm_catalog import ModelCapabilities

TError = TypeVar("TError")


@dataclasses.dataclass(frozen=True)
class _SelectionProviderModel:
    """Resolved model view used by built-in tool validation."""

    model_identifier: str
    capabilities: ModelCapabilities


@dataclasses.dataclass(frozen=True)
class NormalizedSelectableModelOptions:
    """Normalized selectable model option list and effective selections."""

    selectable_model_options: list[SelectableModelOption]
    main_model_label: str
    lightweight_model_label: str
    model_selection: AgentModelSelection
    lightweight_model_selection: AgentModelSelection


def _normalize_requested_label(label: str | None) -> str | None:
    """Trim an optional selected label."""
    if label is None:
        return None
    return label.strip()


def _normalize_subagent_guidance(guidance: str | None) -> str | None:
    """Trim optional subagent guidance and collapse blank input to null."""
    if guidance is None:
        return None
    normalized = guidance.strip()
    return normalized or None


def _select_label(
    labels: set[str], options: Sequence[SelectableModelOption], label: str | None
) -> str:
    """Select a valid label or fall back to the first option label."""
    normalized_label = _normalize_requested_label(label)
    if normalized_label is not None and normalized_label in labels:
        return normalized_label
    return options[0].label


def _normalize_selectable_model_settings(
    *,
    settings_input: SelectableModelSettingsInput | None,
    selection: AgentModelSelection,
) -> Result[SelectableModelSettings, list[str]]:
    """Normalize and validate settings against one resolved model snapshot."""
    if settings_input is None:
        return Success(default_selectable_model_settings(selection))

    builtin_tools = settings_input.builtin_tools
    if builtin_tools is None:
        builtin_tools = default_selectable_model_settings(selection).builtin_tools

    errors: list[str] = []
    names = [tool.name for tool in builtin_tools]
    if len(names) != len(set(names)):
        errors.append("Built-in tool names must be unique.")

    validation_errors = validate_builtin_tools(
        builtin_tools,
        BuiltinToolValidationContext(
            provider_model=_SelectionProviderModel(
                model_identifier=selection.model_identifier,
                capabilities=selection.normalized_capabilities,
            )
        ),
    )
    for tool_errors in validation_errors.values():
        errors.extend(tool_errors)
    if errors:
        return Failure(errors)

    return Success(
        SelectableModelSettings(
            context_window_tokens=settings_input.context_window_tokens,
            max_output_tokens=settings_input.max_output_tokens,
            builtin_tools=list(builtin_tools),
        )
    )


def normalize_stored_selectable_model_options(
    *,
    selectable_model_options: Sequence[SelectableModelOption],
    main_model_label: str | None,
    lightweight_model_label: str | None,
) -> NormalizedSelectableModelOptions:
    """Normalize selected labels against already-resolved options."""
    labels = {option.label for option in selectable_model_options}
    effective_main_label = _select_label(
        labels, selectable_model_options, main_model_label
    )
    effective_lightweight_label = _select_label(
        labels,
        selectable_model_options,
        lightweight_model_label,
    )
    option_by_label = {option.label: option for option in selectable_model_options}
    return NormalizedSelectableModelOptions(
        selectable_model_options=list(selectable_model_options),
        main_model_label=effective_main_label,
        lightweight_model_label=effective_lightweight_label,
        model_selection=option_by_label[effective_main_label]
        .candidates[0]
        .model_selection,
        lightweight_model_selection=option_by_label[effective_lightweight_label]
        .candidates[0]
        .model_selection,
    )


async def normalize_selectable_model_options(
    *,
    option_inputs: Sequence[SelectableModelOptionInput],
    main_model_label: str | None,
    lightweight_model_label: str | None,
    resolve_model_selection: Callable[
        [SelectableModelCandidateInput], Awaitable[Result[AgentModelSelection, TError]]
    ],
    validate_image_generation_config: Callable[
        [AgentModelSelection, SelectableModelSettings],
        Awaitable[list[str]],
    ],
) -> Result[NormalizedSelectableModelOptions, list[str] | TError]:
    """Validate option labels and resolve model snapshots and settings."""
    errors: list[str] = []
    if len(option_inputs) == 0:
        errors.append("At least one selectable model is required.")
    if len(option_inputs) > MAX_SELECTABLE_MODEL_OPTIONS:
        errors.append("At most 10 selectable models are allowed.")

    labels: set[str] = set()
    normalized_inputs: list[tuple[str, SelectableModelOptionInput]] = []
    for option_input in option_inputs:
        label = option_input.label.strip()
        if not label:
            errors.append("Selectable model label is required.")
            continue
        if len(label) > MAX_SELECTABLE_MODEL_LABEL_LENGTH:
            errors.append("Selectable model label must be 80 characters or fewer.")
            continue
        if label in labels:
            errors.append("Selectable model labels must be unique.")
            continue
        labels.add(label)
        normalized_inputs.append((label, option_input))

    if errors:
        return Failure(errors)

    options: list[SelectableModelOption] = []
    for label, option_input in normalized_inputs:
        if len(option_input.candidates) == 0:
            errors.append(
                f"Selectable model '{label}' requires at least one candidate."
            )
            continue
        if len(option_input.candidates) > MAX_SELECTABLE_MODEL_CANDIDATES:
            errors.append(
                f"Selectable model '{label}' allows at most "
                f"{MAX_SELECTABLE_MODEL_CANDIDATES} candidates."
            )
            continue

        identities: set[tuple[str, str]] = set()
        candidates: list[SelectableModelCandidate] = []
        for candidate_index, candidate_input in enumerate(option_input.candidates):
            identity = (
                candidate_input.model_selection.llm_provider_integration_id,
                candidate_input.model_selection.model_identifier,
            )
            if identity in identities:
                errors.append(
                    f"Selectable model '{label}' candidate identities must be unique."
                )
                continue
            identities.add(identity)

            result = await resolve_model_selection(candidate_input)
            match result:
                case Success(selection):
                    settings_result = _normalize_selectable_model_settings(
                        settings_input=candidate_input.settings,
                        selection=selection,
                    )
                    match settings_result:
                        case Success(settings):
                            image_errors = await validate_image_generation_config(
                                selection,
                                settings,
                            )
                            if image_errors:
                                errors.extend(
                                    f"Selectable model '{label}' candidate "
                                    f"{candidate_index + 1}: {error}"
                                    for error in image_errors
                                )
                            else:
                                candidates.append(
                                    SelectableModelCandidate(
                                        model_selection=selection,
                                        settings=settings,
                                    )
                                )
                        case Failure(settings_errors):
                            errors.extend(
                                f"Selectable model '{label}' candidate "
                                f"{candidate_index + 1}: {error}"
                                for error in settings_errors
                            )
                        case _:
                            raise AssertionError("Unhandled settings result")
                case Failure(error):
                    return Failure(error)
                case _:
                    raise AssertionError("Unhandled model selection result")

        if len(candidates) == len(option_input.candidates):
            options.append(
                SelectableModelOption(
                    label=label,
                    candidates=candidates,
                    subagent_enabled=option_input.subagent_enabled,
                    subagent_guidance=_normalize_subagent_guidance(
                        option_input.subagent_guidance
                    ),
                )
            )

    if errors:
        return Failure(errors)

    selected_labels = {option.label for option in options}
    effective_main_label = _select_label(selected_labels, options, main_model_label)
    effective_lightweight_label = _select_label(
        selected_labels,
        options,
        lightweight_model_label,
    )
    option_by_label = {option.label: option for option in options}
    return Success(
        NormalizedSelectableModelOptions(
            selectable_model_options=options,
            main_model_label=effective_main_label,
            lightweight_model_label=effective_lightweight_label,
            model_selection=option_by_label[effective_main_label]
            .candidates[0]
            .model_selection,
            lightweight_model_selection=option_by_label[effective_lightweight_label]
            .candidates[0]
            .model_selection,
        )
    )
