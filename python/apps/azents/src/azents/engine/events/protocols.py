"""Event runtime adapter protocol."""

import datetime
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    EventPayload,
    TokenUsagePayload,
)
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamTimeoutPolicy,
    ModelStreamWatchdog,
)
from azents.engine.run.failure import FailedRunRetryState
from azents.repos.agent_execution.data import (
    AgentRunCreate,
    EventCreate,
)


class NativeModelRequest(BaseModel):
    """Adapter native model request."""

    model_config = ConfigDict(frozen=True)

    model: str = Field(description="Model name")
    input: list[dict[str, object]] = Field(description="Native input items")
    tools: list[dict[str, object]] = Field(default_factory=list)
    kwargs: dict[str, object] = Field(default_factory=dict)


class NativeEvent(BaseModel):
    """Adapter native stream event wrapper."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(description="Native event type")
    item: dict[str, object] = Field(description="Native event payload")


class StreamProjection(BaseModel):
    """UI streaming projection event."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(description="Projection type")
    delta: str | None = Field(default=None)
    index: int | None = Field(default=None)
    call_id: str | None = Field(default=None)
    name: str | None = Field(default=None)


class NormalizedAdapterOutput(BaseModel):
    """Adapter output normalization result."""

    model_config = ConfigDict(frozen=True)

    needs_follow_up: bool = Field(
        description="Whether the model explicitly requested another model step"
    )
    events: list[Event] = Field(default_factory=list)
    projections: list[StreamProjection] = Field(default_factory=list)
    usage: TokenUsagePayload | None = Field(default=None)


class ClientToolExecutor(Protocol):
    """Client tool call executor."""

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Run client tool call and return event result."""
        ...

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        """Request running client tool call cancellation fire-and-forget."""
        ...


class PreLowerFilter(Protocol):
    """Event transcript pre-lower filter."""

    was_compacted: bool

    async def apply(
        self,
        session: AsyncSession,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Normalize Event transcript before lowerer input."""
        ...


class AdapterLowerer(Protocol):
    """Lower Event transcript to adapter native request."""

    compat_key: str

    def lower(
        self,
        transcript: Sequence[Event],
        *,
        model: str,
        system_prompt: str | None = None,
    ) -> NativeModelRequest:
        """Convert Event transcript to native request."""
        ...


class PostLowerFilter(Protocol):
    """Adapter native request post-processing filter."""

    def apply(self, request: NativeModelRequest) -> NativeModelRequest:
        """Validate or modify native request."""
        ...


class ModelAdapter(Protocol):
    """Adapter native model transport."""

    def stream(
        self,
        request: NativeModelRequest,
        *,
        watchdog: ModelStreamWatchdog,
        timeout_policy: ModelStreamTimeoutPolicy,
        call_context: ModelStreamCallContext,
    ) -> AsyncIterator[NativeEvent]:
        """Return native stream event."""
        ...


class AdapterOutputStream(Protocol):
    """Incrementally normalize one adapter-native model stream."""

    def process_event(
        self,
        native_event: NativeEvent,
    ) -> NormalizedAdapterOutput:
        """Convert one native event to immediate live projections."""
        ...

    def complete(self) -> NormalizedAdapterOutput:
        """Build durable output after the native stream completes."""
        ...

    def interrupt(self) -> NormalizedAdapterOutput:
        """Build preservable partial output after user interruption."""
        ...


class AdapterOutputNormalizer(Protocol):
    """Create incremental normalizers for adapter-native model streams."""

    def start(self, session_id: str) -> AdapterOutputStream:
        """Start normalization state for one native model stream."""
        ...


class AgentRunCreateRepository(Protocol):
    """Agent run create repository protocol."""

    async def get_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState | None:
        """Fetch run state."""
        ...

    async def create(
        self,
        session: AsyncSession,
        create: AgentRunCreate,
    ) -> AgentRunState:
        """Create Agent run row."""
        ...

    async def mark_terminal(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime.datetime,
        last_completed_event_id: str | None = None,
        terminal_result_event_id: str | None = None,
        terminal_result_message: str | None = None,
    ) -> object:
        """Record run terminal state."""
        ...

    async def update_retry_state(
        self,
        session: AsyncSession,
        run_id: str,
        retry_state: FailedRunRetryState | None,
    ) -> object:
        """Set or clear durable failed-run retry state."""
        ...


class RunStateRepository(Protocol):
    """Agent run state repository protocol."""

    async def lock_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState | None:
        """Fetch run state with a row lock."""
        ...

    async def get_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState | None:
        """Fetch run state."""
        ...

    async def update_phase(
        self,
        session: AsyncSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> AgentRunState:
        """Update run phase."""
        ...

    async def mark_terminal(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime.datetime,
        last_completed_event_id: str | None = None,
        terminal_result_event_id: str | None = None,
        terminal_result_message: str | None = None,
    ) -> object:
        """Record run terminal state."""
        ...

    async def update_retry_state(
        self,
        session: AsyncSession,
        run_id: str,
        retry_state: FailedRunRetryState | None,
    ) -> object:
        """Set or clear durable failed-run retry state."""
        ...


class TranscriptRepository(Protocol):
    """Event transcript repository protocol."""

    async def list_for_model_input(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        head_event_id: str | None = None,
    ) -> list[Event]:
        """Fetch model input transcript."""
        ...

    async def append(
        self,
        session: AsyncSession,
        create: EventCreate,
    ) -> Event:
        """Append Event."""
        ...

    async def get_by_external_id(
        self,
        session: AsyncSession,
        session_id: str,
        external_id: str,
    ) -> Event | None:
        """Find event by external ID."""
        ...


class EventPayloadRepository(Protocol):
    """Event payload mutation repository."""

    async def update_payload(
        self,
        session: AsyncSession,
        event_id: str,
        payload: EventPayload,
    ) -> Event:
        """Update payload."""
        ...


class SessionHeadMoveRepository(Protocol):
    """Session head update repository."""

    async def move_model_input_head(
        self,
        session: AsyncSession,
        session_id: str,
        event_id: str,
    ) -> object:
        """Move model input head."""
        ...


class EventAppendRepository(EventPayloadRepository, Protocol):
    """Event append/update repository."""

    async def append(
        self,
        session: AsyncSession,
        create: EventCreate,
    ) -> Event:
        """Append Event."""
        ...

    async def update_model_orders(
        self,
        session: AsyncSession,
        session_id: str,
        order_by_event_id: dict[str, int],
    ) -> None:
        """Update Event model input logical order."""
        ...


class SessionHeadState(Protocol):
    """Session state with model input head."""

    model_input_head_event_id: str | None
    model_input_head_model_order: int | None


class SessionHeadRepository(Protocol):
    """Event session head lookup repository protocol."""

    async def get_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> SessionHeadState | None:
        """Fetch session state."""
        ...


class SummaryEnricher(Protocol):
    """Compaction summary enrichment callback protocol."""

    async def __call__(
        self,
        *,
        summary: str,
        continuity_history: str,
        compaction_id: str,
        reason: str | None,
        covered_until_event_id: str,
    ) -> str:
        """Return enriched summary without continuity appended."""
        ...


class ManualCompactor(Protocol):
    """Manual event compaction protocol."""

    async def compact(
        self,
        *,
        session_id: str,
        transcript: Sequence[Event],
        compaction_id: str,
        summarize: "SummaryGenerator",
        on_started: Callable[[], Awaitable[None]] | None = None,
        summary_context_window_tokens: int | None = None,
        reason: str | None = None,
        summary_enricher: SummaryEnricher | None = None,
    ) -> Event | None:
        """Run append-only compaction."""
        ...


SummaryGenerator = Callable[[Sequence[Event], Any], Awaitable[str]]
OutputSink = Callable[
    [NormalizedAdapterOutput, Sequence[Event]],
    Awaitable[None],
]
