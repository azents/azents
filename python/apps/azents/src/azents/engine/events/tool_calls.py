"""Durable client tool-call admission and finalization primitives."""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.engine.client_tools import ClientToolWireDialect
from azents.engine.events.protocols import RunStateRepository, TranscriptRepository
from azents.engine.events.types import (
    ClientToolResultPayload,
    Event,
)
from azents.repos.agent_execution.data import EventCreate


class ToolCallIdentity(Protocol):
    """Minimal admitted call identity needed for terminal finalization."""

    call_id: str
    name: str
    wire_dialect: ClientToolWireDialect


def tool_call_external_id(run_id: str, call_id: str) -> str:
    """Return the deterministic durable identity for one client tool call."""
    return f"tool-call:{run_id}:{call_id}"


def tool_result_external_id(run_id: str, call_id: str) -> str:
    """Return the sole deterministic terminal-result identity for one call."""
    return f"tool-result:{run_id}:{call_id}"


async def finalize_tool_result(
    session: AsyncSession,
    *,
    run_repo: RunStateRepository,
    transcript_repo: TranscriptRepository,
    run_id: str,
    session_id: str,
    call: ToolCallIdentity,
    result: ClientToolResultPayload,
) -> Event:
    """Append one terminal result and remove only its active ownership entry."""
    if result.call_id != call.call_id:
        raise ValueError("Tool result call ID does not match admitted call")
    if result.wire_dialect != call.wire_dialect:
        raise ValueError("Tool result dialect does not match admitted call")
    event = await transcript_repo.append(
        session,
        EventCreate(
            session_id=session_id,
            kind=EventKind.CLIENT_TOOL_RESULT,
            payload=result.model_dump(mode="json", exclude_none=True),
            external_id=tool_result_external_id(run_id, call.call_id),
        ),
    )
    run_state = await run_repo.lock_by_id(session, run_id)
    if run_state is None:
        raise ValueError("Agent run not found")
    if run_state.status == AgentRunStatus.RUNNING:
        remaining = [
            active
            for active in run_state.active_tool_calls
            if active.call_id != call.call_id
        ]
        await run_repo.update_phase(
            session,
            run_id,
            AgentRunPhase.EXECUTING_TOOLS
            if remaining
            else AgentRunPhase.APPENDING_EVENTS,
            active_tool_calls=remaining,
        )
    return event
