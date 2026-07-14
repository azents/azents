"""User stop finalization."""

import asyncio
import dataclasses
import datetime
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Annotated, TypeVar

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionOwnershipLostError
from azents.core.enums import AgentRunStatus, EventKind
from azents.engine.events.engine_events import RunStopped
from azents.engine.events.tool_calls import (
    finalize_tool_result,
    tool_call_external_id,
    tool_result_external_id,
)
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
from azents.rdb.deps import get_session_manager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.services.chat.live_events import RedisLiveEventStore
from azents.worker.deps import get_live_event_store, get_worker_broker
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.live.event_projector import LiveEventProjector

SessionManagerFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_T = TypeVar("_T")
logger = logging.getLogger(__name__)

_PRE_COMMIT_SNAPSHOT_TIMEOUT_SECONDS = 0.25
_EXTERNAL_STEP_TIMEOUT_SECONDS = 1.0
_POST_COMMIT_DELIVERY_TIMEOUT_SECONDS = 10.0
_RETAINED_POST_COMMIT_TASKS: set[asyncio.Task[Exception | None]] = set()


def _on_post_commit_task_done(
    task: asyncio.Task[Exception | None],
    *,
    session_id: str,
) -> None:
    """Release and observe a retained post-commit delivery task."""
    _RETAINED_POST_COMMIT_TASKS.discard(task)
    try:
        delivery_error = task.result()
    except asyncio.CancelledError:
        logger.warning(
            "User stop post-commit delivery task was cancelled",
            extra={"session_id": session_id},
        )
    except Exception:
        logger.exception(
            "User stop post-commit delivery task failed",
            extra={"session_id": session_id},
        )
    else:
        if delivery_error is not None:
            logger.error(
                "User stop post-commit delivery task failed",
                exc_info=(
                    type(delivery_error),
                    delivery_error,
                    delivery_error.__traceback__,
                ),
                extra={"session_id": session_id},
            )


def _retain_post_commit_task(
    task: asyncio.Task[Exception | None],
    *,
    session_id: str,
) -> None:
    """Keep a post-commit delivery alive and always consume its outcome."""
    _RETAINED_POST_COMMIT_TASKS.add(task)
    task.add_done_callback(
        lambda done_task: _on_post_commit_task_done(
            done_task,
            session_id=session_id,
        )
    )


@dataclasses.dataclass(frozen=True)
class _PersistedUserStop:
    """Committed stop state returned before external projection delivery."""

    run_id: str | None
    active_tool_calls: tuple[ActiveToolCall, ...]
    history_events: tuple[Event, ...]
    removable_live_event_ids: tuple[str, ...]
    removed_call_ids: frozenset[str]
    cleanup_activity: bool


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
    ) -> str | None:
        """Immediately clean run observation state as terminal after User stop."""
        live_events: Sequence[Event] = await self._run_external_step(
            session_id,
            step="capture_live_event_snapshot",
            action=lambda: self._capture_live_event_snapshot(session_id),
            default=(),
            timeout=_PRE_COMMIT_SNAPSHOT_TIMEOUT_SECONDS,
        )
        persisted = await self._persist_stop_transaction(
            session_id,
            run_id=run_id,
            reported_active_tool_calls=active_tool_calls,
            live_events=live_events,
        )
        if not persisted.cleanup_activity:
            return persisted.run_id
        regular_history_events = tuple(
            event
            for event in persisted.history_events
            if event.kind not in {EventKind.INTERRUPTED, EventKind.RUN_MARKER}
        )
        terminal_history_events = tuple(
            event
            for event in persisted.history_events
            if event.kind in {EventKind.INTERRUPTED, EventKind.RUN_MARKER}
        )

        delivery_task = asyncio.create_task(
            self._deliver_committed_stop(
                session_id,
                persisted=persisted,
                regular_history_events=regular_history_events,
                terminal_history_events=terminal_history_events,
            ),
            name=f"user-stop-post-commit:{session_id}",
        )
        _retain_post_commit_task(delivery_task, session_id=session_id)
        delivery_error = await asyncio.shield(delivery_task)
        if delivery_error is not None:
            raise delivery_error
        return persisted.run_id

    async def _deliver_committed_stop(
        self,
        session_id: str,
        *,
        persisted: _PersistedUserStop,
        regular_history_events: Sequence[Event],
        terminal_history_events: Sequence[Event],
    ) -> Exception | None:
        """Deliver one committed stop sequence under a hard deadline."""
        try:
            async with asyncio.timeout(_POST_COMMIT_DELIVERY_TIMEOUT_SECONDS):
                await self._deliver_committed_stop_steps(
                    session_id,
                    persisted=persisted,
                    regular_history_events=regular_history_events,
                    terminal_history_events=terminal_history_events,
                )
        except TimeoutError:
            logger.warning(
                "User stop post-commit delivery timed out",
                extra={"session_id": session_id},
            )
        except Exception as exc:
            return exc
        return None

    async def _deliver_committed_stop_steps(
        self,
        session_id: str,
        *,
        persisted: _PersistedUserStop,
        regular_history_events: Sequence[Event],
        terminal_history_events: Sequence[Event],
    ) -> None:
        """Deliver committed stop signals and cleanup in order."""
        for event in terminal_history_events:
            await self._run_external_step(
                session_id,
                step=f"dispatch_stop_{event.kind.value}",
                action=lambda event=event: self.event_publisher.dispatch_event(
                    session_id,
                    event,
                ),
                default=None,
                timeout=None,
            )
        persisted_run_id = persisted.run_id
        if persisted_run_id is not None:
            await self._run_external_step(
                session_id,
                step="dispatch_run_stopped",
                action=lambda: self.event_publisher.dispatch_event(
                    session_id,
                    RunStopped(run_id=persisted_run_id),
                ),
                default=None,
                timeout=None,
            )
        if regular_history_events:
            await self._run_external_step(
                session_id,
                step="dispatch_stop_history",
                action=lambda: self._dispatch_history_events(
                    session_id,
                    regular_history_events,
                ),
                default=None,
                timeout=None,
            )
        if persisted_run_id is not None:
            await self._run_external_step(
                session_id,
                step="publish_live_run_cleared",
                action=lambda: self.live_event_projector.publish_live_run_cleared(
                    session_id,
                    run_id=persisted_run_id,
                ),
                default=None,
                timeout=None,
            )
            await self._run_external_step(
                session_id,
                step="clear_active_tool_calls",
                action=lambda: self.live_event_projector.replace_active_tool_calls(
                    session_id,
                    [],
                    run_id=persisted_run_id,
                    removed_call_ids=set(persisted.removed_call_ids),
                ),
                default=None,
                timeout=None,
            )
            await self._run_external_step(
                session_id,
                step="remove_stop_live_events",
                action=lambda: self._remove_persisted_stop_live_events(
                    session_id,
                    run_id=persisted_run_id,
                    event_ids=persisted.removable_live_event_ids,
                ),
                default=None,
                timeout=None,
            )
            await self._run_external_step(
                session_id,
                step="clear_session_activity",
                action=lambda: self.broker.clear_session_activity_for_run(
                    session_id,
                    run_id=persisted_run_id,
                ),
                default=None,
                timeout=None,
            )
        else:
            orphan_projection_cleared = await self._run_external_step(
                session_id,
                step="clear_orphan_live_projection",
                action=lambda: self.live_event_projector.clear_session_if_no_active_run(
                    session_id
                ),
                default=False,
                timeout=None,
            )
            if orphan_projection_cleared:
                await self._run_external_step(
                    session_id,
                    step="clear_orphan_session_activity",
                    action=lambda: self.broker.clear_session_activity(session_id),
                    default=None,
                    timeout=None,
                )

    async def record_interrupted_run(
        self,
        session_id: str,
        *,
        run_id: str,
        active_tool_calls: Sequence[ActiveToolCall],
    ) -> None:
        """Finalize a cancellation while its running projection is still available."""
        await self.finalize(
            session_id,
            run_id=run_id,
            active_tool_calls=active_tool_calls,
        )

    async def _persist_stop_transaction(
        self,
        session_id: str,
        *,
        run_id: str | None,
        reported_active_tool_calls: Sequence[ActiveToolCall],
        live_events: Sequence[Event],
    ) -> _PersistedUserStop:
        """Atomically persist stop history/state without external I/O."""

        async def persist(db_session: AsyncSession) -> _PersistedUserStop:
            agent_session = await self.agent_session_repository.lock_by_id(
                db_session,
                session_id,
            )
            if agent_session is None:
                raise ValueError("AgentSession not found")

            active_run = None
            implicit_terminal_recovery = False
            if run_id is not None:
                active_run = await self.agent_run_repository.lock_by_id(
                    db_session,
                    run_id,
                )
                latest_by_session_id = (
                    await self.agent_run_repository.list_latest_by_session_ids(
                        db_session,
                        session_ids=[session_id],
                    )
                )
                latest = latest_by_session_id.get(session_id)
                stale_explicit_run = active_run is not None and (
                    active_run.session_id != session_id
                    or (latest is not None and latest.id != active_run.id)
                    or _run_stop_intent_conflicts(
                        active_run,
                        stop_requested_at=agent_session.stop_requested_at,
                    )
                )
                if stale_explicit_run:
                    assert active_run is not None
                    return _PersistedUserStop(
                        run_id=active_run.id,
                        active_tool_calls=(),
                        history_events=(),
                        removable_live_event_ids=(),
                        removed_call_ids=frozenset(),
                        cleanup_activity=False,
                    )
            else:
                candidate = await self.agent_run_repository.get_active_by_session_id(
                    db_session,
                    session_id=session_id,
                )
                if candidate is not None:
                    active_run = await self.agent_run_repository.lock_by_id(
                        db_session,
                        candidate.id,
                    )
                elif agent_session.stop_requested_at is not None:
                    latest_by_session_id = (
                        await self.agent_run_repository.list_latest_by_session_ids(
                            db_session,
                            session_ids=[session_id],
                        )
                    )
                    latest = latest_by_session_id.get(session_id)
                    if latest is not None and _terminal_run_matches_stop_intent(
                        latest,
                        stop_requested_at=agent_session.stop_requested_at,
                    ):
                        active_run = await self.agent_run_repository.lock_by_id(
                            db_session,
                            latest.id,
                        )
                if agent_session.stop_requested_at is not None:
                    implicit_terminal_recovery = _terminal_run_matches_stop_intent(
                        active_run,
                        stop_requested_at=agent_session.stop_requested_at,
                    )

            explicit_recovery_statuses = {
                AgentRunStatus.INTERRUPTED,
                AgentRunStatus.STOPPED,
            }
            active_statuses = {AgentRunStatus.PENDING, AgentRunStatus.RUNNING}
            recoverable = (
                active_run is not None
                and active_run.session_id == session_id
                and (
                    active_run.status in active_statuses
                    or (
                        (run_id is not None or implicit_terminal_recovery)
                        and active_run.status in explicit_recovery_statuses
                    )
                )
            )
            if not recoverable:
                cleanup_activity = run_id is None and active_run is None
                if cleanup_activity:
                    (
                        history_events,
                        removable_live_event_ids,
                    ) = await self._append_live_partial_events(
                        db_session,
                        session_id,
                        live_events,
                        replay_existing=False,
                    )
                else:
                    history_events, removable_live_event_ids = [], ()
                if run_id is None or active_run is not None:
                    await self.agent_session_repository.clear_stop_request(
                        db_session,
                        session_id=session_id,
                    )
                return _PersistedUserStop(
                    run_id=None,
                    active_tool_calls=(),
                    history_events=tuple(history_events),
                    removable_live_event_ids=removable_live_event_ids,
                    removed_call_ids=frozenset(
                        event.payload.call_id
                        for event in live_events
                        if isinstance(event.payload, ClientToolCallPayload)
                    ),
                    cleanup_activity=cleanup_activity,
                )

            if active_run is None:
                raise AssertionError("Recoverable AgentRun is required")
            recovering_terminal = active_run.status in explicit_recovery_statuses and (
                run_id is not None or implicit_terminal_recovery
            )
            active_tool_calls = tuple(active_run.active_tool_calls)
            if recovering_terminal:
                recovered_tool_calls = await self._validated_recovery_tool_calls(
                    db_session,
                    session_id,
                    run_id=active_run.id,
                    reported_active_tool_calls=reported_active_tool_calls,
                )
                calls_by_id = {call.call_id: call for call in active_tool_calls}
                calls_by_id.update(
                    {call.call_id: call for call in recovered_tool_calls}
                )
                active_tool_calls = tuple(calls_by_id.values())
            (
                history_events,
                removable_live_event_ids,
            ) = await self._append_live_partial_events(
                db_session,
                session_id,
                live_events,
                replay_existing=recovering_terminal,
            )
            durable_live_tool_event_ids = (
                await self._validated_durable_live_tool_event_ids(
                    db_session,
                    session_id,
                    run_id=active_run.id,
                    live_events=live_events,
                )
            )
            history_events.extend(
                await self._append_cancelled_tool_results(
                    db_session,
                    session_id,
                    run_id=active_run.id,
                    active_tool_calls=active_tool_calls,
                    replay_existing=recovering_terminal,
                )
            )
            history_events.extend(
                await self._append_user_stop_events(
                    db_session,
                    session_id,
                    active_run.id,
                    replay_existing=recovering_terminal,
                )
            )
            terminal_result_event_id = active_run.terminal_result_event_id
            terminal_result_message = active_run.terminal_result_message
            if terminal_result_event_id is None and terminal_result_message is None:
                for event in reversed(history_events):
                    if not isinstance(event.payload, AssistantMessagePayload):
                        continue
                    message = _assistant_content_text(event.payload.content)
                    if message is not None:
                        terminal_result_event_id = event.id
                        terminal_result_message = message
                        break
            if active_run.status != AgentRunStatus.STOPPED:
                await self.agent_run_repository.mark_stopped_for_user_stop(
                    db_session,
                    active_run.id,
                    ended_at=datetime.datetime.now(datetime.UTC),
                    last_completed_event_id=active_run.last_completed_event_id,
                    terminal_result_event_id=terminal_result_event_id,
                    terminal_result_message=terminal_result_message,
                )

            await self.agent_session_repository.clear_stop_request(
                db_session,
                session_id=session_id,
            )
            return _PersistedUserStop(
                run_id=active_run.id,
                active_tool_calls=active_tool_calls,
                history_events=tuple(history_events),
                removable_live_event_ids=(
                    *removable_live_event_ids,
                    *durable_live_tool_event_ids,
                ),
                removed_call_ids=frozenset(
                    {call.call_id for call in active_tool_calls}
                    | {
                        event.payload.call_id
                        for event in live_events
                        if isinstance(event.payload, ClientToolCallPayload)
                    }
                ),
                cleanup_activity=True,
            )

        return await self._run_short_db(persist)

    async def _append_live_partial_events(
        self,
        db_session: AsyncSession,
        session_id: str,
        live_events: Sequence[Event],
        *,
        replay_existing: bool,
    ) -> tuple[list[Event], tuple[str, ...]]:
        """Append live assistant/reasoning projection to durable history."""
        appendable = [
            event
            for event in live_events
            if isinstance(event.payload, AssistantMessagePayload | ReasoningPayload)
        ]
        if not appendable:
            return [], ()

        appended: list[Event] = []
        removable_live_event_ids: list[str] = []
        for event in appendable:
            get_by_external_id = self.event_transcript_repository.get_by_external_id
            existing = await get_by_external_id(
                db_session,
                session_id,
                event.id,
            )
            if existing is not None:
                removable_live_event_ids.append(event.id)
                if replay_existing:
                    appended.append(existing)
                continue
            appended.append(
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
            )
            removable_live_event_ids.append(event.id)
        return appended, tuple(removable_live_event_ids)

    async def _append_user_stop_events(
        self,
        db_session: AsyncSession,
        session_id: str,
        run_id: str,
        *,
        replay_existing: bool,
    ) -> list[Event]:
        """Record User stop event and run marker to durable history."""
        interrupted_external_id = f"interrupted:{run_id}:user_requested"
        marker_external_id = f"run-marker:{run_id}:interrupted"
        appended: list[Event] = []
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
            appended.append(
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
            )
        elif replay_existing:
            appended.append(interrupted_existing)

        marker_existing = await self.event_transcript_repository.get_by_external_id(
            db_session,
            session_id,
            marker_external_id,
        )
        if marker_existing is None:
            payload = RunMarkerPayload(run_id=run_id, status="interrupted")
            appended.append(
                await self.event_transcript_repository.append(
                    db_session,
                    EventCreate(
                        session_id=session_id,
                        kind=EventKind.RUN_MARKER,
                        payload=payload.model_dump(mode="json", exclude_none=True),
                        external_id=marker_external_id,
                    ),
                )
            )
        elif replay_existing:
            appended.append(marker_existing)
        return appended

    async def _append_cancelled_tool_results(
        self,
        db_session: AsyncSession,
        session_id: str,
        *,
        run_id: str | None,
        active_tool_calls: Sequence[ActiveToolCall],
        replay_existing: bool,
    ) -> list[Event]:
        """Record cancelled result for Active tool call to durable history."""
        calls_by_id = {call.call_id: call for call in active_tool_calls}
        if not calls_by_id:
            return []
        if run_id is None:
            raise RuntimeError("Active tool calls require a running AgentRun")

        appended: list[Event] = []
        for call in calls_by_id.values():
            external_id = tool_result_external_id(run_id, call.call_id)
            existing = await self.event_transcript_repository.get_by_external_id(
                db_session,
                session_id,
                external_id,
            )
            if existing is not None:
                if replay_existing:
                    appended.append(existing)
                continue
            payload = ClientToolResultPayload(
                call_id=call.call_id,
                name=call.name,
                status="cancelled",
                output=[
                    OutputTextPart(
                        text=(
                            "Tool execution was cancelled before a result was recorded."
                        ),
                    )
                ],
            )
            appended.append(
                await finalize_tool_result(
                    db_session,
                    run_repo=self.agent_run_repository,
                    transcript_repo=self.event_transcript_repository,
                    run_id=run_id,
                    session_id=session_id,
                    owner_generation=None,
                    call=call,
                    result=payload,
                )
            )
        return appended

    async def _validated_recovery_tool_calls(
        self,
        db_session: AsyncSession,
        session_id: str,
        *,
        run_id: str,
        reported_active_tool_calls: Sequence[ActiveToolCall],
    ) -> tuple[ActiveToolCall, ...]:
        """Keep reported calls only when their durable admission matches the Run."""
        recovered: list[ActiveToolCall] = []
        for call in reported_active_tool_calls:
            durable_call = await self.event_transcript_repository.get_by_external_id(
                db_session,
                session_id,
                tool_call_external_id(run_id, call.call_id),
            )
            if durable_call is None or not isinstance(
                durable_call.payload,
                ClientToolCallPayload,
            ):
                continue
            if (
                durable_call.payload.call_id != call.call_id
                or durable_call.payload.name != call.name
            ):
                continue
            recovered.append(call)
        return tuple(recovered)

    async def _validated_durable_live_tool_event_ids(
        self,
        db_session: AsyncSession,
        session_id: str,
        *,
        run_id: str,
        live_events: Sequence[Event],
    ) -> tuple[str, ...]:
        """Return captured tool projections whose durable admission is confirmed."""
        confirmed: list[str] = []
        for event in live_events:
            if not isinstance(event.payload, ClientToolCallPayload):
                continue
            durable_call = await self.event_transcript_repository.get_by_external_id(
                db_session,
                session_id,
                tool_call_external_id(run_id, event.payload.call_id),
            )
            if durable_call is None or not isinstance(
                durable_call.payload,
                ClientToolCallPayload,
            ):
                continue
            if (
                durable_call.payload.call_id != event.payload.call_id
                or durable_call.payload.name != event.payload.name
            ):
                continue
            confirmed.append(event.id)
        return tuple(confirmed)

    async def _remove_persisted_stop_live_events(
        self,
        session_id: str,
        *,
        run_id: str,
        event_ids: tuple[str, ...],
    ) -> None:
        """Remove only captured projections confirmed durable by the transaction."""
        for event_id in event_ids:
            await self.live_event_projector.remove_event(
                session_id,
                event_id,
                run_id=run_id,
            )

    async def _capture_live_event_snapshot(
        self,
        session_id: str,
    ) -> Sequence[Event]:
        """Flush and load one live snapshot within a shared pre-commit budget."""
        await self.live_event_projector.flush_session(session_id)
        return await self.live_event_store.list_by_session_id(session_id)

    async def _dispatch_history_events(
        self,
        session_id: str,
        events: Sequence[Event],
    ) -> None:
        """Publish committed durable history events in append order."""
        for event in events:
            await self.event_publisher.dispatch_event(session_id, event)

    async def _run_short_db(
        self,
        action: Callable[[AsyncSession], Awaitable[_T]],
    ) -> _T:
        """Run ``action`` in a short-lived DB transaction."""
        async with self.session_manager() as db_session:
            return await action(db_session)

    async def _run_external_step(
        self,
        session_id: str,
        *,
        step: str,
        action: Callable[[], Awaitable[_T]],
        default: _T,
        timeout: float | None,
    ) -> _T:
        """Run one non-DB projection step without blocking durable finalization."""
        effective_timeout = (
            _EXTERNAL_STEP_TIMEOUT_SECONDS if timeout is None else timeout
        )
        try:
            async with asyncio.timeout(effective_timeout):
                return await action()
        except asyncio.CancelledError:
            raise
        except SessionOwnershipLostError:
            # Ownership loss is a control-flow fence, not a best-effort
            # projection failure. Stop before a stale finalizer can execute any
            # later direct projector or broker cleanup.
            raise
        except TimeoutError:
            logger.warning(
                "User stop external step timed out",
                extra={"session_id": session_id, "step": step},
            )
        except Exception:
            logger.exception(
                "User stop external step failed",
                extra={"session_id": session_id, "step": step},
            )
        return default


def _terminal_run_matches_stop_intent(
    run: AgentRunState | None,
    *,
    stop_requested_at: datetime.datetime,
) -> bool:
    """Return whether the latest Run terminalized for the current stop intent."""
    return (
        run is not None
        and run.status in {AgentRunStatus.INTERRUPTED, AgentRunStatus.STOPPED}
        and run.ended_at is not None
        and (
            run.stop_requested_at == stop_requested_at
            or (run.stop_requested_at is None and run.ended_at >= stop_requested_at)
        )
    )


def _run_stop_intent_conflicts(
    run: AgentRunState,
    *,
    stop_requested_at: datetime.datetime | None,
) -> bool:
    """Return whether an explicit old Run would consume a newer stop intent."""
    return stop_requested_at is not None and (
        (
            run.stop_requested_at is not None
            and run.stop_requested_at != stop_requested_at
        )
        or (
            run.stop_requested_at is None
            and run.ended_at is not None
            and run.ended_at < stop_requested_at
        )
    )


def _assistant_content_text(content: object) -> str | None:
    """Extract terminal-result text from one assistant projection."""
    if isinstance(content, str):
        stripped = content.strip()
        return stripped or None
    if isinstance(content, list):
        parts = [
            part.text.strip() for part in content if isinstance(part, OutputTextPart)
        ]
        text = "\n".join(part for part in parts if part)
        return text or None
    return None
