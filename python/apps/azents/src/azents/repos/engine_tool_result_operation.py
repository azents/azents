"""Completed database operations for Engine client tool results."""

import dataclasses
from typing import Protocol

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.engine.client_tools import ClientToolWireDialect
from azents.engine.events.types import (
    ActiveToolCall,
    ClientToolResultPayload,
    Event,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution.data import EventCreate


class ToolCallIdentity(Protocol):
    """Minimal admitted call identity needed for terminal finalization."""

    @property
    def call_id(self) -> str:
        """Return the admitted tool call identifier."""
        ...

    @property
    def name(self) -> str:
        """Return the admitted tool name."""
        ...

    @property
    def wire_dialect(self) -> ClientToolWireDialect:
        """Return the admitted provider wire dialect."""
        ...


class ToolResultRunState(Protocol):
    """Detached Run fields used by tool-result admission."""

    @property
    def status(self) -> AgentRunStatus:
        """Return current Run status."""
        ...

    @property
    def active_tool_calls(self) -> list[ActiveToolCall]:
        """Return active tool-call ownership entries."""
        ...


class ToolResultRunRepository(Protocol):
    """Run mutations required by tool-result admission."""

    async def lock_by_id(
        self,
        session: WriteSession,
        run_id: str,
    ) -> ToolResultRunState | None:
        """Lock and return one AgentRun."""
        ...

    async def update_phase(
        self,
        session: WriteSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> object:
        """Update phase and active tool-call ownership."""
        ...


class ToolResultTranscriptRepository(Protocol):
    """Transcript append operation required by tool-result admission."""

    async def append(
        self,
        session: WriteSession,
        create: EventCreate,
    ) -> Event:
        """Append one durable Event."""
        ...


def tool_result_external_id(run_id: str, call_id: str) -> str:
    """Return the sole deterministic terminal-result identity for one call."""
    return f"tool-result:{run_id}:{call_id}"


@dataclasses.dataclass(frozen=True)
class EngineToolResultOperationRepository:
    """Own completed client tool-result admission transactions."""

    session_manager: SessionManager[WriteSession]
    run_repository: ToolResultRunRepository
    transcript_repository: ToolResultTranscriptRepository

    async def finalize(
        self,
        *,
        run_id: str,
        session_id: str,
        call: ToolCallIdentity,
        result: ClientToolResultPayload,
    ) -> Event:
        """Finalize one tool result in a completed transaction."""
        async with self.session_manager() as session:
            return await self.finalize_in_session(
                session,
                run_id=run_id,
                session_id=session_id,
                call=call,
                result=result,
            )

    async def finalize_in_session(
        self,
        session: WriteSession,
        *,
        run_id: str,
        session_id: str,
        call: ToolCallIdentity,
        result: ClientToolResultPayload,
    ) -> Event:
        """Finalize one tool result inside a composing repository transaction."""
        if result.call_id != call.call_id:
            raise ValueError("Tool result call ID does not match admitted call")
        if result.wire_dialect != call.wire_dialect:
            raise ValueError("Tool result dialect does not match admitted call")
        event = await self.transcript_repository.append(
            session,
            EventCreate(
                session_id=session_id,
                kind=EventKind.CLIENT_TOOL_RESULT,
                payload=result.model_dump(mode="json", exclude_none=True),
                external_id=tool_result_external_id(run_id, call.call_id),
            ),
        )
        run_state = await self.run_repository.lock_by_id(session, run_id)
        if run_state is None:
            raise ValueError("Agent run not found")
        if run_state.status is AgentRunStatus.RUNNING:
            remaining = [
                active
                for active in run_state.active_tool_calls
                if active.call_id != call.call_id
            ]
            await self.run_repository.update_phase(
                session,
                run_id,
                AgentRunPhase.EXECUTING_TOOLS
                if remaining
                else AgentRunPhase.APPENDING_EVENTS,
                active_tool_calls=remaining,
            )
        return event
