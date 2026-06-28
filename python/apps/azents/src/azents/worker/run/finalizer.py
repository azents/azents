"""Shared failed-run finalization helpers."""

import dataclasses
import datetime
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import PublishedEvent
from azents.core.enums import AgentRunStatus, EventKind
from azents.engine.events.engine_events import RunComplete
from azents.engine.events.types import Event, RunMarkerPayload, SystemErrorPayload
from azents.engine.run.failure import (
    FailedRunFailureMetadata,
    FailedRunFinalizationReason,
    FailedRunRetryState,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.worker.session.lifecycle import SessionLifecycleService


@dataclasses.dataclass(frozen=True)
class FailedRunFinalizationInput:
    """Input for terminal failed-run finalization."""

    session_id: str
    run_id: str
    user_message: str
    retry_state: FailedRunRetryState
    reason: FailedRunFinalizationReason
    action_hint: str | None = None


@dataclasses.dataclass(frozen=True)
class FailedRunFinalizationResult:
    """Events created/emitted during failed-run finalization."""

    error_event: Event
    run_marker: Event


@dataclasses.dataclass(frozen=True)
class FailedRunErrorFinalizer:
    """Promote the latest failed attempt to terminal durable failed-run output."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    session_lifecycle: Annotated[
        SessionLifecycleService, Depends(SessionLifecycleService)
    ]

    async def finalize(
        self,
        input: FailedRunFinalizationInput,
        *,
        dispatch_event: Callable[[str, PublishedEvent], Awaitable[None]],
    ) -> FailedRunFinalizationResult:
        """Append terminal failed-run output and close the run as failed."""
        metadata = FailedRunFailureMetadata.from_retry_state(
            input.retry_state,
            finalization_reason=input.reason,
            action_hint=input.action_hint,
        )
        async with self.session_manager() as session:
            error_event = await self.event_transcript_repository.append(
                session,
                EventCreate(
                    session_id=input.session_id,
                    kind=EventKind.SYSTEM_ERROR,
                    payload=SystemErrorPayload(
                        content=input.user_message,
                        severity="error",
                        recoverable=True,
                        failure=metadata,
                    ).model_dump(mode="json", exclude_none=True),
                    external_id=f"failed-run:{input.run_id}:system-error",
                ),
            )
            run_marker = await self.event_transcript_repository.append(
                session,
                EventCreate(
                    session_id=input.session_id,
                    kind=EventKind.RUN_MARKER,
                    payload=RunMarkerPayload(
                        run_id=input.run_id,
                        status="failed",
                        error=input.user_message,
                    ).model_dump(mode="json", exclude_none=True),
                    external_id=f"failed-run:{input.run_id}:run-marker",
                ),
            )
            await self.agent_run_repository.mark_terminal_if_running(
                session,
                input.run_id,
                AgentRunStatus.FAILED,
                ended_at=datetime.datetime.now(datetime.UTC),
                last_completed_event_id=run_marker.id,
            )
        await dispatch_event(input.session_id, error_event)
        await dispatch_event(input.session_id, run_marker)
        await dispatch_event(input.session_id, RunComplete())
        await self.session_lifecycle.clear_session_activity(input.session_id)
        return FailedRunFinalizationResult(
            error_event=error_event,
            run_marker=run_marker,
        )
