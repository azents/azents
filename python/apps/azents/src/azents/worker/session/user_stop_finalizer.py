"""User stop finalization."""

import dataclasses
import datetime
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker
from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.engine.events.engine_events import RunStopped
from azents.engine.events.tool_calls import finalize_tool_result
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    InterruptedPayload,
    OutputTextPart,
    ReasoningPayload,
    RunMarkerPayload,
)
from azents.engine.run.failure import RunRecoveryState
from azents.rdb.deps import get_session_manager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.services.chat.data import ChatLiveRunRecoveryState, ChatLiveRunState
from azents.services.chat.live_events import RedisLiveEventStore
from azents.worker.deps import get_live_event_store, get_worker_broker
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.live.event_projector import LiveEventProjector

SessionManagerFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class UserStopFinalizer:
    """Clean up run observation state after receiving User stop."""

    session_manager: Annotated[SessionManagerFactory, Depends(get_session_manager)]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    live_event_store: Annotated[RedisLiveEventStore, Depends(get_live_event_store)]
    live_event_projector: Annotated[LiveEventProjector, Depends(LiveEventProjector)]
    event_publisher: Annotated[WorkerEventPublisher, Depends(WorkerEventPublisher)]
    broker: Annotated[SessionBroker, Depends(get_worker_broker)]

    async def finalize(
        self,
        session_id: str,
        *,
        run_id: str | None,
        active_tool_calls: Sequence[ActiveToolCall],
    ) -> None:
        """Immediately clean run observation state as terminal after User stop."""
        del active_tool_calls
        running_run = await self._get_running_agent_run(session_id)
        effective_run_id = run_id or (
            running_run.id if running_run is not None else None
        )
        effective_tool_calls = (
            list(running_run.active_tool_calls) if running_run is not None else []
        )
        await self.live_event_projector.flush_session(session_id)
        await self._persist_live_events_for_user_stop(
            session_id,
            run_id=effective_run_id,
            active_tool_calls=effective_tool_calls,
        )
        await self.live_event_projector.replace_active_tool_calls(
            session_id,
            [],
            removed_call_ids={call.call_id for call in effective_tool_calls},
        )
        if effective_run_id is not None:
            await self._append_user_stop_events(session_id, effective_run_id)
        if effective_run_id is None:
            await self._mark_session_agent_runs_terminal(
                session_id,
                status=AgentRunStatus.STOPPED,
            )
            await self._clear_stop_request(session_id)
        else:
            stopped_run = await self._mark_agent_run_stopped_with_recovery(
                session_id,
                run_id=effective_run_id,
                recovery_state=_stopped_recovery_state(running_run),
            )
            await self._clear_stop_request(session_id)
            await self.event_publisher.dispatch_event(
                session_id,
                RunStopped(run_id=effective_run_id),
            )
            await self._publish_stopped_recovery(session_id, stopped_run)
        await self.broker.clear_session_activity(session_id)

    async def record_interrupted_run(
        self,
        session_id: str,
        *,
        run_id: str,
    ) -> None:
        """Record run marker stopped by User stop and RunStopped event."""
        running_run = await self._get_running_agent_run(session_id)
        await self._append_user_stop_events(session_id, run_id)
        stopped_run = await self._mark_agent_run_stopped_with_recovery(
            session_id,
            run_id=run_id,
            recovery_state=_stopped_recovery_state(running_run),
        )
        await self._clear_stop_request(session_id)
        await self.event_publisher.dispatch_event(
            session_id,
            RunStopped(run_id=run_id),
        )
        await self._publish_stopped_recovery(session_id, stopped_run)

    async def _get_running_agent_run(
        self,
        session_id: str,
    ) -> AgentRunState | None:
        """Fetch current running AgentRun projection."""
        async with self.session_manager() as db_session:
            return await self.agent_run_repository.get_running_by_session_id(
                db_session,
                session_id=session_id,
            )

    async def _persist_live_events_for_user_stop(
        self,
        session_id: str,
        *,
        run_id: str | None,
        active_tool_calls: Sequence[ActiveToolCall],
    ) -> None:
        """Promote live projection to durable history on Stop critical path."""
        live_events = await self.live_event_store.list_by_session_id(session_id)
        await self._append_live_partial_events(session_id, live_events)
        await self._append_cancelled_tool_results(
            session_id,
            run_id=run_id,
            active_tool_calls=active_tool_calls,
        )
        await self._remove_persisted_stop_live_events(session_id, live_events)

    async def _append_live_partial_events(
        self,
        session_id: str,
        live_events: Sequence[Event],
    ) -> None:
        """Append live assistant/reasoning projection to durable history."""
        appendable = [
            event
            for event in live_events
            if isinstance(event.payload, AssistantMessagePayload | ReasoningPayload)
        ]
        if not appendable:
            return

        async def append(db_session: AsyncSession) -> None:
            for event in appendable:
                get_by_external_id = self.event_transcript_repository.get_by_external_id
                existing = await get_by_external_id(
                    db_session,
                    session_id,
                    event.id,
                )
                if existing is not None:
                    continue
                await self.event_transcript_repository.append(
                    db_session,
                    EventCreate(
                        session_id=session_id,
                        kind=event.kind,
                        payload=event.payload.model_dump(
                            mode="json",
                            exclude_none=True,
                        ),
                        external_id=event.id,
                        adapter=event.adapter,
                        provider=event.provider,
                        model=event.model,
                        native_format=event.native_format,
                        schema_version=event.schema_version,
                    ),
                )

        await self._run_short_db(append)

    async def _append_user_stop_events(
        self,
        session_id: str,
        run_id: str,
    ) -> None:
        """Record User stop event and run marker to durable history."""
        interrupted_external_id = f"interrupted:{run_id}:user_requested"
        marker_external_id = f"run-marker:{run_id}:interrupted"

        async def append(db_session: AsyncSession) -> None:
            interrupted_existing = (
                await self.event_transcript_repository.get_by_external_id(
                    db_session,
                    session_id,
                    interrupted_external_id,
                )
            )
            if interrupted_existing is None:
                interrupted_payload = InterruptedPayload(
                    run_id=run_id,
                    reason="user_requested",
                )
                await self.event_transcript_repository.append(
                    db_session,
                    EventCreate(
                        session_id=session_id,
                        kind=EventKind.INTERRUPTED,
                        payload=interrupted_payload.model_dump(
                            mode="json",
                            exclude_none=True,
                        ),
                        external_id=interrupted_external_id,
                    ),
                )

            marker_existing = await self.event_transcript_repository.get_by_external_id(
                db_session,
                session_id,
                marker_external_id,
            )
            if marker_existing is not None:
                return
            payload = RunMarkerPayload(run_id=run_id, status="interrupted")
            await self.event_transcript_repository.append(
                db_session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.RUN_MARKER,
                    payload=payload.model_dump(mode="json", exclude_none=True),
                    external_id=marker_external_id,
                ),
            )

        await self._run_short_db(append)

    async def _clear_stop_request(self, session_id: str) -> None:
        """Remove consumed durable stop intent."""

        async def clear(db_session: AsyncSession) -> None:
            await self.agent_session_repository.clear_stop_request(
                db_session,
                session_id=session_id,
            )

        await self._run_short_db(clear)

    async def _append_cancelled_tool_results(
        self,
        session_id: str,
        *,
        run_id: str | None,
        active_tool_calls: Sequence[ActiveToolCall],
    ) -> None:
        """Record cancelled result for Active tool call to durable history."""
        calls_by_id = {call.call_id: call for call in active_tool_calls}
        if not calls_by_id:
            return
        if run_id is None:
            raise RuntimeError("Active tool calls require a running AgentRun")

        async def append(db_session: AsyncSession) -> None:
            for call in calls_by_id.values():
                payload = ClientToolResultPayload(
                    call_id=call.call_id,
                    name=call.name,
                    status="cancelled",
                    output=[
                        OutputTextPart(
                            text=(
                                "Tool execution was cancelled before a result was "
                                "recorded."
                            ),
                        )
                    ],
                )
                await finalize_tool_result(
                    db_session,
                    run_repo=self.agent_run_repository,
                    transcript_repo=self.event_transcript_repository,
                    run_id=run_id,
                    session_id=session_id,
                    call=call,
                    result=payload,
                )

        await self._run_short_db(append)

    async def _remove_persisted_stop_live_events(
        self,
        session_id: str,
        live_events: Sequence[Event],
    ) -> None:
        """Remove stop-related live projections converged to History."""
        for event in live_events:
            if isinstance(event.payload, AssistantMessagePayload | ReasoningPayload):
                await self.live_event_projector.remove_event(session_id, event.id)
                continue
            if isinstance(event.payload, ClientToolCallPayload):
                await self.live_event_projector.remove_event(session_id, event.id)

    async def _mark_session_agent_runs_terminal(
        self,
        session_id: str,
        *,
        status: AgentRunStatus,
    ) -> None:
        """Close remaining running AgentRun projections when session is idle."""
        await self._run_short_db(
            lambda db: self.agent_run_repository.mark_session_running_terminal(
                db,
                session_id=session_id,
                status=status,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
        )

    async def _mark_agent_run_stopped_with_recovery(
        self,
        session_id: str,
        *,
        run_id: str,
        recovery_state: RunRecoveryState | None,
    ) -> AgentRunState | None:
        """Stop one Run while retaining its latest provider failure."""
        stopped_run: AgentRunState | None = None

        async def mark_stopped(db_session: AsyncSession) -> None:
            nonlocal stopped_run
            run = await self.agent_run_repository.get_by_id(db_session, run_id)
            if run is not None and run.session_id != session_id:
                raise ValueError("AgentRun session mismatch")
            stopped_run = (
                await self.agent_run_repository.mark_stopped_with_recovery_if_running(
                    db_session,
                    run_id,
                    recovery_state=recovery_state,
                    ended_at=datetime.datetime.now(datetime.UTC),
                )
            )

        await self._run_short_db(mark_stopped)
        return stopped_run

    async def _publish_stopped_recovery(
        self,
        session_id: str,
        run: AgentRunState | None,
    ) -> None:
        """Publish the persisted recoverable stopped Run to live clients."""
        if run is None or run.recovery_state is None:
            return
        async with self.session_manager() as db_session:
            session_state = await self.agent_session_repository.get_by_id(
                db_session,
                session_id,
            )
        if session_state is None or session_state.inference_state is None:
            logger.warning(
                "Stopped AgentRun recovery has no Session inference state",
                extra={"session_id": session_id, "run_id": run.id},
            )
            return
        recovery = run.recovery_state
        await self.live_event_projector.publish_live_run_updated(
            session_id,
            ChatLiveRunState(
                run_id=run.id,
                phase=run.phase,
                status=run.status,
                inference_profile=session_state.inference_state.applied_profile,
                model_call_started_at=run.model_call_started_at,
                recovery=ChatLiveRunRecoveryState(
                    kind=recovery.kind,
                    user_message=recovery.user_message,
                    operation=recovery.operation,
                    source_run_id=recovery.source_run_id,
                    stopped_at=recovery.stopped_at.isoformat(),
                ),
            ),
        )

    async def _run_short_db(
        self,
        action: Callable[[AsyncSession], Awaitable[object]],
    ) -> None:
        """Run ``action`` in a short-lived DB transaction."""
        async with self.session_manager() as db_session:
            await action(db_session)


def _stopped_recovery_state(run: AgentRunState | None) -> RunRecoveryState | None:
    """Build a recoverable state for every active Run stopped by the user."""
    if run is None:
        return None
    stopped_at = datetime.datetime.now(datetime.UTC)
    if run.retry_state is not None:
        provider_recovery = RunRecoveryState.from_retry_state(
            run.retry_state,
            source_run_id=run.id,
            stopped_at=stopped_at,
        )
        if provider_recovery is not None:
            return provider_recovery
    return RunRecoveryState(
        kind="stopped",
        user_message="Execution stopped.",
        operation=(
            "compaction" if run.phase is AgentRunPhase.COMPACTING else "sampling"
        ),
        source_run_id=run.id,
        stopped_at=stopped_at,
    )
