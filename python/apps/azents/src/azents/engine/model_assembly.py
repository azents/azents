"""Captured physical-candidate authority for provider-native wire assembly."""

import dataclasses

from azents.core.agent import AgentModelSelection
from azents.core.enums import LLMModelDeveloper
from azents.core.llm_catalog import ModelCapabilities


@dataclasses.dataclass(frozen=True)
class ModelAssemblyMetadata:
    """Saved family dialect evidence, separate from credentials and model identity."""

    model_developer: LLMModelDeveloper | None
    model_family: str | None
    capabilities: ModelCapabilities

    @classmethod
    def from_selection(cls, selection: AgentModelSelection) -> "ModelAssemblyMetadata":
        """Freeze the selected candidate without consulting mutable catalog state."""
        return cls(
            model_developer=selection.model_developer,
            model_family=selection.model_family,
            capabilities=selection.normalized_capabilities.model_copy(deep=True),
        )
