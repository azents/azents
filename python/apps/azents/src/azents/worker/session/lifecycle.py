"""Session lifecycle state and ownership management."""

import asyncio
import dataclasses
import datetime
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, TypeVar

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.agent import AgentModelSelection
from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.inference_profile import (
    InferenceProfileFailureCode,
    InferenceProfileSource,
    InferenceRunSummary,
    RequestedInferenceProfile,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.types import ActiveToolCall, AgentRunState, Event
from azents.engine.run.failure import FailedRunRetryState
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.worker.deps import get_worker_broker

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


@dataclasses.dataclass(frozen=True)
class InferenceRunEventProjection:
    """Durable input event paired with its latest safe run summary."""

    event: Event
    inference_run_summary: InferenceRunSummary


@dataclasses.dataclass(frozen=True)
class SessionLifecycleService:
    """Manage Session runtime state and broker ownership/activity."""

    broker: Annotated[SessionBroker, Depends(get_worker_broker)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]

    async def release_session_lock(self, session_id: str) -> None:
        """Release session lock."""
        await self.broker.release_session_lock(session_id)

    async def clear_session_activity(self, session_id: str) -> None:
        """Remove session activity."""
        await self.broker.clear_session_activity(session_id)

    async def send_session_wake_up(self, message: SessionWakeUp) -> None:
        """Send wake-up through the existing session broker path."""
        await self.broker.send_message(message)

    async def set_session_activity(
        self,
        session_id: str,
        *,
        run_id: str,
        phase: AgentRunPhase | None = None,
        active_tool_calls: Sequence[ActiveToolCall] = (),
    ) -> None:
        """Record session activity and refresh TTL."""
        await self.broker.set_session_activity(
            session_id,
            run_id=run_id,
            phase=phase,
            active_tool_calls=active_tool_calls,
        )

    async def renew_session_owner_heartbeat(self, session_id: str) -> None:
        """Refresh Redis session owner heartbeat."""
        await self.broker.renew_session_owner_heartbeat(session_id)

    async def mark_session_running(self, session_id: str) -> None:
        """Transition ``run_state`` to RUNNING and initialize heartbeat."""
        await self.run_short_db(
            lambda db: self.agent_session_repository.mark_running(db, session_id),
            error_log="Failed to mark session running",
            session_id=session_id,
        )

    async def mark_session_idle(self, session_id: str) -> bool:
        """Revert ``run_state`` to IDLE only after all runs are terminal."""

        async def mark_idle_if_no_run(db_session: AsyncSession) -> bool:
            active_run = await self.agent_run_repository.get_active_by_session_id(
                db_session,
                session_id=session_id,
            )
            if active_run is not None:
                logger.info(
                    "Skipped session idle transition because an AgentRun is active",
                    extra={
                        "session_id": session_id,
                        "run_id": active_run.id,
                    },
                )
                return False
            await self.agent_session_repository.mark_idle(db_session, session_id)
            return True

        marked_idle = await self.run_short_db(
            mark_idle_if_no_run,
            error_log="Failed to mark session idle",
            session_id=session_id,
            default=False,
        )
        return bool(marked_idle)

    async def has_active_agent_run(self, session_id: str) -> bool:
        """Return whether the session still has a pending or running AgentRun."""

        async def get_active(db_session: AsyncSession) -> bool:
            active_run = await self.agent_run_repository.get_active_by_session_id(
                db_session,
                session_id=session_id,
            )
            return active_run is not None

        active = await self.run_short_db(
            get_active,
            error_log="Failed to check active agent run",
            session_id=session_id,
            default=True,
        )
        return bool(active)

    async def list_inference_run_event_projections(
        self,
        *,
        run_id: str,
    ) -> list[InferenceRunEventProjection]:
        """Load associated input events with their latest safe run summaries."""
        async with self.session_manager() as db_session:
            event_ids = await self.agent_run_repository.list_input_event_ids(
                db_session,
                run_id=run_id,
            )
            run_repo = self.agent_run_repository
            summaries = await run_repo.list_latest_inference_run_summaries_by_event_ids(
                db_session,
                event_ids=event_ids,
            )
            projections: list[InferenceRunEventProjection] = []
            for event_id in event_ids:
                event = await self.event_transcript_repository.get_by_id(
                    db_session,
                    event_id=event_id,
                )
                summary = summaries.get(event_id)
                if event is not None and summary is not None:
                    projections.append(
                        InferenceRunEventProjection(
                            event=event,
                            inference_run_summary=summary,
                        )
                    )
            return projections

    async def heartbeat_session(self, session_id: str) -> None:
        """Refresh DB heartbeat and Redis owner heartbeat of RUNNING session."""
        await self.run_short_db(
            lambda db: self.agent_session_repository.heartbeat_running(db, session_id),
            error_log="Failed to heartbeat session",
            session_id=session_id,
        )
        await self.broker.renew_session_owner_heartbeat(session_id)

    async def has_stop_request(self, session_id: str) -> bool:
        """Return whether Durable stop intent exists."""
        async with self.session_manager() as db_session:
            return await self.agent_session_repository.has_stop_request(
                db_session,
                session_id,
            )

    async def claim_recoverable_agent_run(
        self,
        session_id: str,
    ) -> AgentRunState | None:
        """Return the session's activated or pending recoverable run."""
        async with self.session_manager() as db_session:
            running = await self.agent_run_repository.get_running_by_session_id(
                db_session,
                session_id=session_id,
            )
            if running is not None:
                return running
            pending = await self.agent_run_repository.claim_pending_by_session_id(
                db_session,
                session_id=session_id,
            )
            await db_session.commit()
            return pending

    async def create_or_claim_pending_agent_run(
        self,
        session_id: str,
        *,
        requested_profile: RequestedInferenceProfile,
        source: InferenceProfileSource,
        input_event_ids: Sequence[str],
    ) -> AgentRunState:
        """Claim a recoverable pending run or create one for requested input."""
        async with self.session_manager() as db_session:
            pending = await self.agent_run_repository.claim_pending_by_session_id(
                db_session,
                session_id=session_id,
            )
            created = pending is None
            if pending is None:
                pending = await self.agent_run_repository.create_pending(
                    db_session,
                    session_id=session_id,
                    requested_model_target_label=(requested_profile.model_target_label),
                    requested_reasoning_effort=requested_profile.reasoning_effort,
                    inference_profile_source=source,
                    parent_agent_run_id=None,
                    resolved_model_selection=None,
                    resolved_reasoning_effort=None,
                    resolved_at=None,
                    effective_context_window_tokens=None,
                    effective_auto_compaction_threshold_tokens=None,
                )
            pending_profile_matches = (
                pending.requested_model_target_label
                == requested_profile.model_target_label
                and pending.requested_reasoning_effort
                == requested_profile.reasoning_effort
            )
            if not created and not pending_profile_matches:
                raise ValueError("Pending AgentRun inference profile mismatch")
            await self.agent_run_repository.associate_input_events(
                db_session,
                run_id=pending.id,
                event_ids=input_event_ids,
            )
            await db_session.commit()
            return pending

    async def cancel_pending_agent_run(
        self,
        session_id: str,
        *,
        run_id: str,
    ) -> AgentRunState:
        """Cancel a newly created pending run that produced no model work."""
        async with self.session_manager() as db_session:
            run = await self.agent_run_repository.get_by_id(db_session, run_id)
            if (
                run is None
                or run.session_id != session_id
                or run.status != AgentRunStatus.PENDING
            ):
                raise ValueError("Pending AgentRun not found in session")
            cancelled = await self.agent_run_repository.mark_terminal(
                db_session,
                run_id,
                AgentRunStatus.CANCELLED,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
            await db_session.commit()
            return cancelled

    async def activate_pending_agent_run(
        self,
        session_id: str,
        *,
        run_id: str,
        resolved_model_selection: AgentModelSelection,
        resolved_reasoning_effort: ModelReasoningEffort | None,
        effective_context_window_tokens: int,
        effective_auto_compaction_threshold_tokens: int,
    ) -> AgentRunState:
        """Commit resolved provenance and session profile before invocation."""
        async with self.session_manager() as db_session:
            run = await self.agent_run_repository.activate_pending(
                db_session,
                run_id=run_id,
                resolved_model_selection=resolved_model_selection,
                resolved_reasoning_effort=resolved_reasoning_effort,
                resolved_at=datetime.datetime.now(datetime.UTC),
                effective_context_window_tokens=effective_context_window_tokens,
                effective_auto_compaction_threshold_tokens=(
                    effective_auto_compaction_threshold_tokens
                ),
            )
            if run.session_id != session_id:
                raise ValueError("AgentRun session mismatch")
            await db_session.commit()
            return run

    async def fail_pending_agent_run_profile(
        self,
        session_id: str,
        *,
        run_id: str,
        failure_code: InferenceProfileFailureCode,
        failure_message: str,
    ) -> AgentRunState:
        """Finalize a profile resolution failure without changing session intent."""
        async with self.session_manager() as db_session:
            run = await self.agent_run_repository.fail_pending_profile_resolution(
                db_session,
                run_id=run_id,
                failure_code=failure_code,
                failure_message=failure_message,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
            if run.session_id != session_id:
                raise ValueError("AgentRun session mismatch")
            await db_session.commit()
            return run

    async def associate_agent_run_input_events(
        self,
        session_id: str,
        *,
        run_id: str,
        event_ids: Sequence[str],
    ) -> None:
        """Associate exact-profile continuation events with an active run."""
        async with self.session_manager() as db_session:
            run = await self.agent_run_repository.get_by_id(db_session, run_id)
            if run is None or run.session_id != session_id:
                raise ValueError("AgentRun not found in session")
            await self.agent_run_repository.associate_input_events(
                db_session,
                run_id=run_id,
                event_ids=event_ids,
            )
            await db_session.commit()

    async def mark_session_agent_runs_terminal(
        self,
        session_id: str,
        *,
        status: AgentRunStatus,
    ) -> None:
        """Close remaining running AgentRun projections when session is idle."""
        await self.run_short_db(
            lambda db: self.agent_run_repository.mark_session_running_terminal(
                db,
                session_id=session_id,
                status=status,
                ended_at=datetime.datetime.now(datetime.UTC),
            ),
            error_log="Failed to mark session agent runs terminal",
            session_id=session_id,
        )

    async def fail_agent_run_profile_resolution_if_running(
        self,
        session_id: str,
        *,
        run_id: str,
        failure_code: InferenceProfileFailureCode,
        failure_message: str,
    ) -> None:
        """Fail a running AgentRun with safe profile-resolution details."""
        await self.run_short_db(
            lambda db: self.agent_run_repository.fail_profile_resolution_if_running(
                db,
                run_id=run_id,
                failure_code=failure_code,
                failure_message=failure_message,
                ended_at=datetime.datetime.now(datetime.UTC),
            ),
            error_log="Failed to mark agent run profile resolution failed",
            session_id=session_id,
        )

    async def mark_agent_run_terminal_if_running(
        self,
        session_id: str,
        *,
        run_id: str,
        status: AgentRunStatus,
    ) -> None:
        """Close AgentRun row as terminal state if still running."""
        await self.run_short_db(
            lambda db: self.agent_run_repository.mark_terminal_if_running(
                db,
                run_id,
                status,
                ended_at=datetime.datetime.now(datetime.UTC),
            ),
            error_log="Failed to mark agent run terminal",
            session_id=session_id,
        )

    async def update_agent_run_retry_state(
        self,
        session_id: str,
        *,
        run_id: str,
        retry_state: FailedRunRetryState | None,
    ) -> None:
        """Set or clear the AgentRun retry state."""
        await self.run_short_db(
            lambda db: self.agent_run_repository.update_retry_state(
                db,
                run_id,
                retry_state,
            ),
            error_log="Failed to update agent run retry state",
            session_id=session_id,
        )

    async def run_short_db(
        self,
        action: Callable[[AsyncSession], Awaitable[_T]],
        *,
        error_log: str,
        session_id: str,
        default: _T | None = None,
    ) -> _T | None:
        """Run ``action`` in short-lived DB transaction."""
        try:
            async with self.session_manager() as db_session:
                return await action(db_session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(error_log, extra={"session_id": session_id})
            return default
