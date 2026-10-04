"""Completed local captures and read-only active metadata response projections."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends

from azents.core.active_model_capabilities import (
    CompiledActiveChoices,
    ConfiguredModelIdentity,
    apply_to_options,
    apply_to_selection,
    compile_capture,
)
from azents.core.agent import AgentModelSelection
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.agent.data import Agent
from azents.repos.workspace_model_settings.data import WorkspaceModelSettings


@dataclasses.dataclass(frozen=True)
class ActiveModelCapabilitiesService:
    """Compile same-ID local declarations outside completed capture transactions."""

    repository: Annotated[
        ActiveModelCapabilitiesRepository, Depends(ActiveModelCapabilitiesRepository)
    ]

    async def capture_and_compile(
        self, *, workspace_id: str, selections: Sequence[AgentModelSelection]
    ) -> CompiledActiveChoices:
        captured = await self.repository.capture_exact_choices(
            workspace_id=workspace_id,
            identities=tuple(
                ConfiguredModelIdentity.from_selection(selection)
                for selection in selections
            ),
        )
        return compile_capture(captured, selections=selections)


def apply_to_agent_read(agent: Agent, compiled: CompiledActiveChoices) -> Agent:
    """Project an active response copy; persisted/mutation reads remain untouched."""
    options = apply_to_options(agent.selectable_model_options, compiled)
    return agent.model_copy(
        update={
            "selectable_model_options": options,
            "model_selection": apply_to_selection(agent.model_selection, compiled),
            "lightweight_model_selection": apply_to_selection(
                agent.lightweight_model_selection, compiled
            ),
        }
    )


def apply_to_workspace_read(
    settings: WorkspaceModelSettings, compiled: CompiledActiveChoices
) -> WorkspaceModelSettings:
    """Keep default identities/settings and derive only active response metadata."""
    options = settings.default_selectable_model_options
    main = settings.default_model_selection
    lightweight = settings.default_lightweight_model_selection
    return settings.model_copy(
        update={
            "default_selectable_model_options": (
                apply_to_options(options, compiled) if options is not None else None
            ),
            "default_model_selection": (
                apply_to_selection(main, compiled) if main is not None else None
            ),
            "default_lightweight_model_selection": (
                apply_to_selection(lightweight, compiled)
                if lightweight is not None
                else None
            ),
        }
    )
