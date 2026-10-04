"""Repository-owned, Stop-fenced failed Run output and terminal delivery."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.core.enums import AgentRunStatus, EventKind
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.types import Event, RunMarkerPayload, SystemErrorPayload
from azents.engine.run.failure import (
    FailedRunFailureMetadata,
    FailedRunFinalizationReason,
    FailedRunRetryState,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_execution.ownership import fence_owned_session_mutation
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository


@dataclasses.dataclass(frozen=True)
class FailedRunFinalization:
    """Detached input for the complete failed Run database operation."""

    session_id: str
    owner_generation: int
    run_id: str
    user_message: str
    retry_state: FailedRunRetryState
    reason: FailedRunFinalizationReason
    action_hint: str | None


@dataclasses.dataclass(frozen=True)
class FailedRunFinalizationEvents:
    """Detached error and marker Events for post-commit publication."""

    error_event: Event
    run_marker: Event


@dataclasses.dataclass(frozen=True)
class FailedRunFinalizationOperationRepository:
    """Own failure admission, Events, Run transition and parent delivery atomically."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    terminal_finalization_repository: Annotated[
        TerminalRunFinalizationRepository,
        Depends(TerminalRunFinalizationRepository),
    ]

    async def finalize(
        self,
        input: FailedRunFinalization,
    ) -> FailedRunFinalizationEvents | None:
        """Finish one failure unless the current owned Session has a Stop intent."""
        async with self.session_manager() as session:
            agent_session = await fence_owned_session_mutation(
                session, SessionExecutionOwner(input.session_id, input.owner_generation)
            )
            if agent_session is None:
                raise ValueError("AgentSession not found")
            if agent_session.owner_generation != input.owner_generation:
                raise CanonicalExecutionOwnerGenerationStaleError(
                    "Session owner generation is stale"
                )
            if agent_session.stop_requested_at is not None:
                return None
            return await self.append_terminal_failed_run_in_session(session, input)

    async def append_terminal_failed_run_in_session(
        self,
        session: WriteSession,
        input: FailedRunFinalization,
    ) -> FailedRunFinalizationEvents:
        """Compose failed Events and delivery inside an owned repository scope."""
        await self.terminal_finalization_repository.lock_run_finalization(
            session,
            run_id=input.run_id,
        )
        run = await self.run_repository.get_by_id(session, input.run_id)
        terminal_operations = (
            []
            if run is None or run.model_operation_state is None
            else [
                operation
                for operation in (
                    run.model_operation_state.foreground,
                    run.model_operation_state.compaction,
                )
                if operation is not None and operation.terminal_reason is not None
            ]
        )
        if len(terminal_operations) > 1:
            raise RuntimeError("Failed Run has multiple terminal model operations")
        metadata = FailedRunFailureMetadata.from_retry_state(
            input.retry_state,
            finalization_reason=input.reason,
            action_hint=input.action_hint,
            model_operation=terminal_operations[0] if terminal_operations else None,
        )
        error_event = await self.transcript_repository.append(
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
        run_marker = await self.transcript_repository.append(
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
        await self.run_repository.mark_terminal_if_running(
            session,
            input.run_id,
            AgentRunStatus.FAILED,
            ended_at=datetime.datetime.now(datetime.UTC),
            last_completed_event_id=run_marker.id,
            terminal_result_event_id=error_event.id,
            terminal_result_message=input.user_message,
        )
        await self.terminal_finalization_repository.finalize_run_in_session(
            session,
            run_id=input.run_id,
        )
        return FailedRunFinalizationEvents(
            error_event=error_event,
            run_marker=run_marker,
        )
