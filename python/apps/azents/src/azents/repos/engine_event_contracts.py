"""Database primitive contracts composed only by repository operations."""

import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    Event,
    EventPayload,
)
from azents.engine.run.failure import FailedRunRetryState
from azents.repos.agent_execution.data import AgentRunCreate, EventCreate


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

    async def mark_parent_result_suppressed(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        finalized_at: datetime.datetime,
    ) -> AgentRunState:
        """Suppress direct-parent delivery for an intermediate terminal Run."""
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
    """Session head lookup and update repository."""

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> "SessionHeadState | None":
        """Fetch current model-input head state."""
        ...

    async def lock_compaction_plan_if_current(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        expected_head_event_id: str | None,
        expected_tail_event_id: str,
    ) -> bool:
        """Lock the Session and verify the planned compaction boundaries."""
        ...

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


class SessionHeadState(Protocol):
    """Session state with model input head."""

    model_input_head_event_id: str | None


class SessionHeadRepository(Protocol):
    """Event session head lookup repository protocol."""

    async def get_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> SessionHeadState | None:
        """Fetch session state."""
        ...
