"""Event-store helpers for terminal failed-run finalization."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunStatus, EventKind
from azents.engine.events.protocols import TranscriptRepository
from azents.engine.events.types import Event, RunMarkerPayload, SystemErrorPayload
from azents.engine.run.failure import (
    FailedRunFailureMetadata,
    FailedRunFinalizationReason,
    FailedRunRetryState,
)
from azents.repos.agent_execution import (
    AgentRunNotActiveError,
    AgentRunRepository,
    EventTranscriptRepository,
)
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository


@dataclasses.dataclass(frozen=True)
class FailedRunEventStoreResult:
    """Events appended while finalizing a failed run."""

    error_event: Event
    run_marker: Event


@dataclasses.dataclass(frozen=True)
class FailedRunEventStore:
    """Append terminal failed-run events through the engine event-store boundary."""

    transcript_repo: Annotated[TranscriptRepository, Depends(EventTranscriptRepository)]
    run_repo: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    session_repo: Annotated[AgentSessionRepository, Depends(AgentSessionRepository)]

    async def append_terminal_failed_run(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        run_id: str,
        user_message: str,
        retry_state: FailedRunRetryState,
        reason: FailedRunFinalizationReason,
        action_hint: str | None = None,
    ) -> FailedRunEventStoreResult:
        """Append final failed-run events and close the AgentRun."""
        agent_session = await self.session_repo.lock_by_id(session, session_id)
        if agent_session is None:
            raise ValueError("AgentSession not found")
        run = await self.run_repo.lock_by_id(session, run_id)
        if run is None or run.session_id != session_id:
            raise ValueError("AgentRun not found in session")
        if run.status != AgentRunStatus.RUNNING:
            raise AgentRunNotActiveError(run_id, run.status)

        metadata = FailedRunFailureMetadata.from_retry_state(
            retry_state,
            finalization_reason=reason,
            action_hint=action_hint,
        )
        error_event = await self.transcript_repo.append(
            session,
            EventCreate(
                session_id=session_id,
                kind=EventKind.SYSTEM_ERROR,
                payload=SystemErrorPayload(
                    content=user_message,
                    severity="error",
                    recoverable=True,
                    failure=metadata,
                ).model_dump(mode="json", exclude_none=True),
                external_id=f"failed-run:{run_id}:system-error",
            ),
        )
        run_marker = await self.transcript_repo.append(
            session,
            EventCreate(
                session_id=session_id,
                kind=EventKind.RUN_MARKER,
                payload=RunMarkerPayload(
                    run_id=run_id,
                    status="failed",
                    error=user_message,
                ).model_dump(mode="json", exclude_none=True),
                external_id=f"failed-run:{run_id}:run-marker",
            ),
        )
        terminal = await self.run_repo.mark_terminal_if_running(
            session,
            run_id,
            AgentRunStatus.FAILED,
            ended_at=datetime.datetime.now(datetime.UTC),
            last_completed_event_id=run_marker.id,
            terminal_result_event_id=error_event.id,
            terminal_result_message=user_message,
        )
        if terminal is None or terminal.status != AgentRunStatus.FAILED:
            status = run.status if terminal is None else terminal.status
            raise AgentRunNotActiveError(run_id, status)
        return FailedRunEventStoreResult(error_event=error_event, run_marker=run_marker)
