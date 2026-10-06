"""Purpose-owned consolidation host port over shared provider operations."""

from collections.abc import Sequence
from typing import Protocol

from azents.core.agent import AgentModelSelection
from azents.engine.events.model_messages import TransientModelMessage
from azents.engine.events.protocols import NormalizedAdapterOutput
from azents.engine.events.tools import ToolCatalog
from azents.engine.model_stream import InternalModelStreamCallContext
from azents.engine.provider_model_operation import PreparedModelOperation


class ConsolidationModelCapabilityError(ValueError):
    """The selected Lightweight route is unavailable to this consolidation host."""


class ConsolidationModelPort(Protocol):
    """Shared request boundary supporting purpose-owned admission and test hosts."""

    @property
    def selection(self) -> AgentModelSelection: ...
    @property
    def effective_input_tokens(self) -> int: ...
    @property
    def max_output_tokens(self) -> int | None: ...

    def prepare(
        self,
        messages: Sequence[TransientModelMessage],
        catalog: ToolCatalog,
        *,
        system_prompt: str,
        output_tokens: int | None,
    ) -> PreparedModelOperation: ...

    async def invoke(
        self,
        prepared: PreparedModelOperation,
        *,
        context: InternalModelStreamCallContext,
    ) -> NormalizedAdapterOutput[TransientModelMessage]: ...

    async def close(self) -> None: ...
