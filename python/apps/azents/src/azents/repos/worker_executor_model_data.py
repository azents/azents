"""Detached user configuration and new/frozen Worker preparation facts."""

import dataclasses
import json
from typing import TYPE_CHECKING

from azents.core.active_model_capabilities import CompiledActiveChoices
from azents.core.agent import SelectableModelCandidate, SelectableModelOption
from azents.core.model_operation import ModelOperationSnapshot, ModelOperationState
from azents.engine.events.types import AgentRunState
from azents.repos.agent.data import Agent
from azents.repos.agent_session.data import AgentSession
from azents.repos.model_candidate_selection import ModelCandidateSelection

if TYPE_CHECKING:
    from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs


def agent_model_configuration_signature(agent: Agent) -> str:
    """Compare user intent without compiled capabilities, prices or display metadata."""
    return json.dumps(
        {
            "main": agent.main_model_label,
            "lightweight": agent.lightweight_model_label,
            "parameters": (
                agent.model_parameters.model_dump(mode="json")
                if agent.model_parameters is not None
                else None
            ),
            "options": [
                {
                    "label": option.label,
                    "subagent_enabled": option.subagent_enabled,
                    "subagent_guidance": option.subagent_guidance,
                    "candidates": [
                        {
                            "integration": (
                                candidate.model_selection.llm_provider_integration_id
                            ),
                            "provider": candidate.model_selection.provider.value,
                            "model": candidate.model_selection.model_identifier,
                            "settings": candidate.settings.model_dump(mode="json"),
                        }
                        for candidate in option.candidates
                    ],
                }
                for option in agent.selectable_model_options
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def run_model_intent_signature(run: AgentRunState | None) -> str | None:
    """Fence raw run intent separately from captured capabilities and progress."""
    if run is None:
        return None
    return json.dumps(
        {
            "target": run.requested_model_target_label,
            "effort": run.requested_reasoning_effort,
            "options": run.requested_enabled_execution_options,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def apply_frozen_operation(
    options: list[SelectableModelOption], operation: ModelOperationSnapshot | None
) -> list[SelectableModelOption]:
    """Normalize reused intent against captures rather than current metadata."""
    if operation is None or operation.terminal_reason is not None:
        return options
    return [
        option.model_copy(
            update={
                "candidates": [
                    SelectableModelCandidate(
                        model_selection=candidate.model_selection,
                        settings=candidate.settings,
                    )
                    for candidate in operation.candidates
                ]
            }
        )
        if option.label == operation.semantic_label
        else option
        for option in options
    ]


@dataclasses.dataclass(frozen=True)
class FreshProfileSnapshot:
    """One coherent new/frozen preparation frame before normalization and locking."""

    agent: Agent
    session: AgentSession
    raw_configuration_signature: str
    raw_run_intent_signature: str | None
    operation_state: ModelOperationState | None
    captured_inputs: CapturedActiveChoiceInputs | None
    compiled_choices: CompiledActiveChoices | None
    compaction_option: SelectableModelOption | None


@dataclasses.dataclass(frozen=True)
class FreshModelPreparation:
    """Committed foreground and background selections before external work."""

    selection: ModelCandidateSelection
    compaction_selection: ModelCandidateSelection
    configuration_signature: str
