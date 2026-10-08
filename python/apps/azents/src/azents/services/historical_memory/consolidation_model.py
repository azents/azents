"""Shared model and canonical context ports for private durable Memory execution."""

from collections.abc import Sequence
from typing import Protocol

from azents.core.agent import AgentModelSelection, SelectableModelCandidate
from azents.core.historical_memory_consolidation import (
    MemoryAcceptedOutcome,
    MemoryExecutionPrincipal,
)
from azents.engine.context.compaction import SummaryModelCall
from azents.engine.events.model_messages import TransientModelMessage
from azents.engine.events.protocols import NormalizedAdapterOutput
from azents.engine.events.tools import ToolCatalog
from azents.engine.events.types import TokenUsagePayload
from azents.engine.model_stream import ModelStreamCallContext
from azents.engine.provider_model_operation import PreparedModelOperation
from azents.engine.run.model_transport import ModelTransportState


class ConsolidationModelCapabilityError(ValueError):
    """The selected Lightweight route cannot execute the Memory task."""


class ConsolidationModelPort(Protocol):
    """One shared prepared provider transport; no private model loop or owner."""

    @property
    def selection(self) -> AgentModelSelection: ...

    @property
    def effective_input_tokens(self) -> int: ...

    @property
    def max_output_tokens(self) -> int | None: ...

    @property
    def candidate(self) -> SelectableModelCandidate: ...

    @property
    def credential_kwargs(self) -> dict[str, object]: ...

    @property
    def transport_state(self) -> ModelTransportState: ...

    @property
    def summary_call(self) -> SummaryModelCall: ...

    def prepare(
        self,
        messages: Sequence[TransientModelMessage],
        catalog: ToolCatalog | None,
        *,
        system_prompt: str,
        output_tokens: int | None,
    ) -> PreparedModelOperation: ...

    async def invoke(
        self,
        prepared: PreparedModelOperation,
        *,
        context: ModelStreamCallContext,
    ) -> NormalizedAdapterOutput[TransientModelMessage]: ...

    async def close(self) -> None: ...


class MemoryExecutionContextPort(Protocol):
    """Canonical Event/head operations, using common context and compaction.

    The implementation owns completed database operations and never treats a
    host's transient provider envelopes as the authoritative transcript.
    """

    async def seed(self, principal: MemoryExecutionPrincipal, content: str) -> None:
        """Persist the fresh execution's input guidance once."""
        ...

    async def prepare(
        self,
        principal: MemoryExecutionPrincipal,
        model: ConsolidationModelPort,
        catalog: ToolCatalog,
        *,
        system_prompt: str,
    ) -> PreparedModelOperation:
        """Load canonical context and fit the actual lowered provider request."""
        ...

    async def append(
        self,
        principal: MemoryExecutionPrincipal,
        messages: Sequence[TransientModelMessage],
        *,
        accepted: MemoryAcceptedOutcome | None,
    ) -> None:
        """Commit normalized output or tool results under common owner fencing.

        An accepted result permits its exact original terminal audit append;
        it does not authorize another model call or a successor's writes.
        """
        ...

    async def record_usage(
        self,
        principal: MemoryExecutionPrincipal,
        usage: TokenUsagePayload | None,
    ) -> None:
        """Record common Run/Event usage without a separate dispatch ledger."""
        ...
