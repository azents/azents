"""Per-session worker runner orchestration."""

import asyncio
import dataclasses
import logging
from collections.abc import Sequence
from typing import assert_never

from azcommon.logging import bind_extra
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import (
    BrokerMessage,
    SessionStopSignal,
    SessionWakeUp,
)
from azents.core.enums import AgentRunStatus
from azents.engine.run.contracts import AgentEngineProtocol, ToolkitBinding
from azents.engine.run.errors import UserVisibleRuntimeError
from azents.engine.run.model_transport import ModelTransportState
from azents.engine.run.types import CheckStop, PollMessages, PollMessagesResult
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.services.input_buffer import InputBufferService
from azents.services.subagent_terminal_result import SubagentTerminalResultService
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.run.executor import RunExecutor
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.errors import SessionRunnerErrorReporter
from azents.worker.session.execution_snapshot import (
    CanonicalExecutionOwnerGenerationStaleError,
    CanonicalExecutionSnapshot,
    CanonicalExecutionSnapshotError,
    CanonicalExecutionSnapshotLoader,
    CanonicalExecutionWorkDriftError,
)
from azents.worker.session.idle_continuation import IdleContinuationService
from azents.worker.session.inbox import SessionRunnerInbox
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.supervisor import (
    RunStopController,
    RunTaskSupervisor,
)
from azents.worker.session.toolkit_scope import SessionToolkitScope
from azents.worker.session.user_stop_finalizer import UserStopFinalizer
from azents.worker.session.waiter import (
    HeartbeatResult,
    IdleTimeoutResult,
    MessageResult,
    SessionRunnerWaiter,
    ShutdownResult,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _PendingIdleBoundary:
    """Terminal run boundary to close after a stale wake-up."""

    message: SessionWakeUp
    snapshot: CanonicalExecutionSnapshot
    toolkits: list[ToolkitBinding]
    run_id: str | None
    run_status: AgentRunStatus | None


@dataclasses.dataclass(frozen=True)
class _RunnerLoopState:
    """State carried between session runner ticks."""

    idle_started_at: float


class SessionRunner:
    """Per-session message processing loop.

    Task creation is handled by owner. Constructor only initializes in-memory state;
    when ``run()`` is called, it processes enqueued messages sequentially.
    """

    def __init__(
        self,
        *,
        shutdown_event: asyncio.Event,
        event_publisher: WorkerEventPublisher,
        session_lifecycle: SessionLifecycleService,
        execution_snapshot_loader: CanonicalExecutionSnapshotLoader,
        session_manager: SessionManager[AsyncSession],
        agent_session_repository: AgentSessionRepository,
        input_buffer_service: InputBufferService,
        subagent_terminal_result_service: SubagentTerminalResultService,
        idle_continuation_service: IdleContinuationService,
        user_stop_finalizer: UserStopFinalizer,
        run_executor: RunExecutor,
        engine: AgentEngineProtocol,
        model_transport_state: ModelTransportState,
    ) -> None:
        self.shutdown_event = shutdown_event
        self.event_publisher = event_publisher
        self.session_lifecycle = session_lifecycle
        self.execution_snapshot_loader = execution_snapshot_loader
        self.session_manager = session_manager
        self.agent_session_repository = agent_session_repository
        self.input_buffer_service = input_buffer_service
        self.subagent_terminal_result_service = subagent_terminal_result_service
        self.idle_continuation_service = idle_continuation_service
        self.run_executor = run_executor
        self.model_transport_state = model_transport_state
        self.inbox = SessionRunnerInbox()
        self.runner_shutdown = asyncio.Event()
        self.terminated_event = asyncio.Event()
        self.started = False
        self.stop_controller = RunStopController()
        self.running_session_id: str | None = None
        self.owner_generation: int | None = None
        self.execution_snapshot: CanonicalExecutionSnapshot | None = None
        self.toolkit_scope = SessionToolkitScope()
        self.waiter = SessionRunnerWaiter()
        self.run_supervisor = RunTaskSupervisor(
            run_executor=run_executor,
            user_stop_finalizer=user_stop_finalizer,
            shutdown_event=shutdown_event,
            event_publisher=event_publisher,
            session_lifecycle=session_lifecycle,
            stop_controller=self.stop_controller,
        )
        self.error_reporter = SessionRunnerErrorReporter(
            engine=engine,
            event_publisher=event_publisher,
        )
        self.run_active = False
        self.handover_wake_up: SessionWakeUp | None = None
        self.handover_required = False

    @property
    def terminated(self) -> bool:
        """Whether Runner loop has ended."""
        return self.terminated_event.is_set()

    async def run(self) -> None:
        """Run session message processing loop."""
        if self.started:
            raise RuntimeError("Session runner already started")
        self.started = True
        try:
            await self._loop()
        finally:
            self.terminated_event.set()

    def request_shutdown(self) -> None:
        """Request runner shutdown after current processing completes."""
        self.runner_shutdown.set()

    async def shutdown(self) -> None:
        """Request Runner shutdown and wait until loop exits."""
        self.request_shutdown()
        if self.started:
            await self.terminated_event.wait()
            return
        await self.toolkit_scope.cleanup()
        self.terminated_event.set()

    def enqueue(self, message: BrokerMessage) -> None:
        """Add message to processing queue.

        :param message: Broker message to process
        """
        self.inbox.enqueue(message, stop_controller=self.stop_controller)

    async def prepare_toolkits(
        self,
        toolkits: Sequence[ToolkitBinding],
    ) -> list[ToolkitBinding]:
        """Prepare Session-managed toolkit snapshot."""
        return await self.toolkit_scope.prepare(toolkits)

    def _make_poll_fn(self) -> PollMessages:
        """Create poll_messages callback to inject into engine.run()."""

        async def poll() -> PollMessagesResult:
            self._drain_stop_signals()
            return PollMessagesResult(
                user_messages=[],
                context_invalidated=False,
                complete_run=False,
            )

        return poll

    def _drain_stop_signals(self) -> None:
        """Drain stop requests accumulated in queue and preserve remaining messages."""
        self.inbox.drain_stop_signals(self.stop_controller)

    async def _enqueue_wake_up_after_stop_if_needed(
        self,
        message: SessionWakeUp,
    ) -> None:
        """Wake next turn only when pending buffer remains after Stop."""
        if not self.stop_controller.user_stop_requested:
            return
        has_pending = self.input_buffer_service.has_pending_wake_session_input_buffers
        if not await has_pending(message.session_id):
            discarded = self.inbox.discard_wake_ups(message.session_id)
            if discarded:
                logger.info(
                    "Session runner discarded wake-ups after user stop "
                    "with no pending input",
                    extra={
                        "session_id": message.session_id,
                        "discarded_wake_up_count": discarded,
                    },
                )
            return
        if self.inbox.has_wake_up_queued(message.session_id):
            return
        self.inbox.requeue_wake_up(message)

    def _make_check_stop_fn(self, session_id: str) -> CheckStop:
        """Create check_stop callback to inject into engine.run()."""

        async def check_stop() -> bool:
            self._drain_stop_signals()

            if self.stop_controller.user_stop_requested:
                return True

            if await self.session_lifecycle.has_stop_request(session_id):
                self.stop_controller.request_user_stop()
                return True

            if self.shutdown_event.is_set():
                self.stop_controller.request_handover_stop()
                await self.stop_controller.tool_admission_barrier.close()
                return True

            return False

        return check_stop

    async def _run_with_timeout(
        self,
        message: SessionWakeUp,
        snapshot: CanonicalExecutionSnapshot,
    ) -> RunExecutionResult:
        """Delegate engine execution to stop/shutdown supervisor."""
        if self.owner_generation is None:
            raise RuntimeError("Session ownership generation was not claimed")
        return await self.run_supervisor.run(
            snapshot,
            poll_fn=self._make_poll_fn(),
            check_stop=self._make_check_stop_fn(message.session_id),
            prepare_toolkits=self.prepare_toolkits,
            drain_stop_signals=self._drain_stop_signals,
            model_transport_state=self.model_transport_state,
        )

    async def _clear_activity_after_failed_message(
        self,
        session_id: str,
        *,
        reason: str,
    ) -> None:
        """Clean only live activity after processing failure."""
        try:
            await self.session_lifecycle.clear_session_activity(session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to clear session activity after runner message failed",
                extra={"session_id": session_id, "reason": reason},
            )

    async def _has_follow_up_work(self, session_id: str) -> bool:
        """Return whether terminal run should continue instead of becoming idle."""
        if not self.inbox.empty():
            return True
        if await self._has_pending_command(session_id):
            return True
        has_pending_input = (
            self.input_buffer_service.has_pending_wake_session_input_buffers
        )
        return await has_pending_input(session_id)

    async def _has_pending_command(self, session_id: str) -> bool:
        """Return whether a pending runtime command should run next."""
        async with self.session_manager() as db_session:
            command = (
                await self.agent_session_repository.get_pending_command_by_session_id(
                    db_session,
                    session_id,
                )
            )
        return command is not None

    async def _mark_idle_after_no_actionable_wake_up(
        self,
        session_id: str,
    ) -> bool:
        """Mark a wake-up idle when promotion produced no model work."""
        logger.info(
            "Session runner marking session idle after no-actionable wake-up",
            extra={"session_id": session_id},
        )
        if self.owner_generation is None:
            raise RuntimeError("Session ownership generation was not claimed")
        marked_idle = await self.session_lifecycle.mark_session_idle(
            session_id,
            owner_generation=self.owner_generation,
        )
        if not marked_idle:
            return False
        await self.session_lifecycle.clear_session_activity(session_id)
        return True

    async def _mark_idle_after_boundary(
        self,
        boundary: _PendingIdleBoundary,
    ) -> bool:
        """Close a terminal boundary through its durable idle outcome."""
        logger.info(
            "Session runner marking session idle after terminal run",
            extra={
                "session_id": boundary.message.session_id,
                "run_status": boundary.run_status,
            },
        )
        if boundary.run_status == AgentRunStatus.COMPLETED:
            if boundary.run_id is None:
                raise RuntimeError("Completed run has no idle continuation boundary ID")
            consumed = await self.idle_continuation_service.consume(
                boundary.snapshot,
                toolkits=boundary.toolkits,
                run_id=boundary.run_id,
            )
            if not consumed:
                return False
            await self.session_lifecycle.clear_session_activity(
                boundary.message.session_id
            )
            return True

        marked_idle = await self.session_lifecycle.mark_session_idle(
            boundary.message.session_id,
            owner_generation=boundary.snapshot.owner_generation,
        )
        if not marked_idle:
            return False
        await self.session_lifecycle.clear_session_activity(boundary.message.session_id)
        logger.info(
            "Skipped idle continuation because terminal run did not complete",
            extra={
                "session_id": boundary.message.session_id,
                "run_id": boundary.run_id,
                "run_status": boundary.run_status,
            },
        )
        return True

    async def _release_current_session(self) -> None:
        """Release current session ownership or hand it over to another worker."""
        session_id = self.running_session_id
        if session_id is None:
            return

        wake_up = self.handover_wake_up
        if wake_up is None:
            await self.session_lifecycle.release_session_lock(session_id)
            return

        if self.handover_required:
            await self.session_lifecycle.release_session_lock(session_id)
            await self.session_lifecycle.send_session_wake_up(wake_up)
            return

        should_handover = await self.session_lifecycle.has_active_agent_run(session_id)
        if not should_handover:
            should_handover = (
                await self.session_lifecycle.has_pending_idle_continuation(session_id)
            )

        if not should_handover:
            await self.session_lifecycle.release_session_lock(session_id)
            return

        logger.info(
            "Session runner stopped during active run, handing over session",
            extra={"session_id": session_id},
        )
        await self.session_lifecycle.release_session_lock(session_id)
        try:
            await self.session_lifecycle.send_session_wake_up(wake_up)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to enqueue session handover wake-up",
                extra={"session_id": session_id},
            )

    def _monotonic_time(self) -> float:
        """Return the current event-loop monotonic time."""
        return asyncio.get_running_loop().time()

    async def _loop(self) -> None:
        """Session message processing loop."""
        state: _RunnerLoopState | None = _RunnerLoopState(
            idle_started_at=self._monotonic_time()
        )
        try:
            while state is not None:
                try:
                    state = await self._tick(state)
                except CanonicalExecutionSnapshotError as exc:
                    session_id = self.running_session_id
                    if session_id is None:
                        raise
                    self._handle_canonical_execution_error(
                        SessionWakeUp(session_id=session_id),
                        exc,
                    )
                    state = None
        finally:
            toolkit_cleanup_error: Exception | None = None
            try:
                await self.toolkit_scope.cleanup()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                toolkit_cleanup_error = exc
            if self.running_session_id is not None:
                logger.info(
                    "Session runner stopped, releasing lock",
                    extra={"session_id": self.running_session_id},
                )
                await self._release_current_session()
            if toolkit_cleanup_error is not None:
                raise toolkit_cleanup_error

    async def _tick(
        self,
        state: _RunnerLoopState,
    ) -> _RunnerLoopState | None:
        wait_result = await self.waiter.wait_next(
            inbox=self.inbox,
            runner_shutdown=self.runner_shutdown,
            running_session_id=self.running_session_id,
            idle_started_at=state.idle_started_at,
        )
        match wait_result:
            case HeartbeatResult():
                assert self.running_session_id is not None
                await self.session_lifecycle.renew_session_owner_heartbeat(
                    self.running_session_id
                )
                return state
            case IdleTimeoutResult():
                logger.info(
                    "Session runner idle timeout",
                    extra={"session_id": self.running_session_id},
                )
                return None
            case ShutdownResult():
                return None
            case MessageResult(message):
                if self.running_session_id is None:
                    self.running_session_id = message.session_id
                    self.owner_generation = (
                        await self.session_lifecycle.claim_owner_generation(
                            message.session_id
                        )
                    )
                self.stop_controller.clear_for_next_run()
                self.handover_wake_up = None
                self.handover_required = False
                message_started_at = self._monotonic_time()
                L = bind_extra(
                    logger,
                    {
                        "session_id": message.session_id,
                        "message_type": type(message).__name__,
                    },
                )
                L.info(
                    "Session runner wake-up dequeued",
                    extra={
                        "idle_wait_seconds": round(
                            message_started_at - state.idle_started_at,
                            3,
                        ),
                        "inbox_size": self.inbox.qsize(),
                    },
                )

                result = await self._process_message(message)

                if self.shutdown_event.is_set():
                    return None

                if result.terminal_event_observed and isinstance(
                    message,
                    SessionWakeUp,
                ):
                    delivery_service = self.subagent_terminal_result_service
                    await delivery_service.deliver_pending_for_source_session(
                        message.session_id,
                        repair_source="terminal_boundary",
                    )

                marked_idle = False
                if result.terminal_event_observed:
                    if isinstance(message, SessionWakeUp):
                        snapshot = self.execution_snapshot
                        if snapshot is None:
                            raise RuntimeError(
                                "Session execution snapshot was not loaded"
                            )
                        boundary = _PendingIdleBoundary(
                            message=message,
                            snapshot=snapshot,
                            toolkits=result.toolkits,
                            run_id=result.run_id,
                            run_status=result.terminal_run_status,
                        )
                        if not await self._has_follow_up_work(message.session_id):
                            marked_idle = await self._mark_idle_after_boundary(boundary)
                elif result.no_actionable_work and isinstance(message, SessionWakeUp):
                    snapshot = self.execution_snapshot
                    if snapshot is None:
                        raise RuntimeError("Session execution snapshot was not loaded")
                    pending_run_id = snapshot.pending_idle_continuation_run_id
                    if (
                        pending_run_id is not None
                        and not await self._has_follow_up_work(message.session_id)
                    ):
                        toolkits = (
                            await self.run_executor.resolve_idle_continuation_toolkits(
                                snapshot,
                                run_id=pending_run_id,
                                prepare_toolkits=self.prepare_toolkits,
                                dispatch_event=self.event_publisher.dispatch_event,
                            )
                        )
                        boundary = _PendingIdleBoundary(
                            message=message,
                            snapshot=snapshot,
                            toolkits=toolkits,
                            run_id=pending_run_id,
                            run_status=AgentRunStatus.COMPLETED,
                        )
                        marked_idle = await self._mark_idle_after_boundary(boundary)
                    elif pending_run_id is None and not await self._has_follow_up_work(
                        message.session_id
                    ):
                        marked_idle = await self._mark_idle_after_no_actionable_wake_up(
                            message.session_id
                        )
                L.info(
                    "Session runner wake-up processed",
                    extra={
                        "duration_seconds": round(
                            self._monotonic_time() - message_started_at,
                            3,
                        ),
                        "inbox_size": self.inbox.qsize(),
                        "user_stop_requested": self.stop_controller.user_stop_requested,
                        "runner_shutdown": self.runner_shutdown.is_set(),
                        "marked_idle": marked_idle,
                    },
                )

                if self.runner_shutdown.is_set() and self.inbox.empty():
                    return None
                return _RunnerLoopState(idle_started_at=self._monotonic_time())
            case _:
                assert_never(wait_result)

    async def _process_message(self, message: BrokerMessage) -> RunExecutionResult:
        """Handle one Broker message."""
        try:
            match message:
                case SessionStopSignal():
                    return RunExecutionResult(
                        toolkits=[],
                        terminal_event_observed=False,
                        no_actionable_work=False,
                    )
                case SessionWakeUp():
                    return await self._process_wake_up(message)
                case _:
                    assert_never(message)
        except asyncio.CancelledError:
            raise
        except CanonicalExecutionSnapshotError as exc:
            return self._handle_canonical_execution_error(message, exc)
        except UserVisibleRuntimeError as exc:
            try:
                finalized_run_id = (
                    await self.run_executor.finalize_unhandled_active_run(
                        message.session_id,
                        exc,
                        owner_generation=self._required_owner_generation(),
                        dispatch_event=self.event_publisher.dispatch_event,
                    )
                )
            except CanonicalExecutionOwnerGenerationStaleError as stale:
                return self._handle_canonical_execution_error(message, stale)
            if finalized_run_id is not None:
                return RunExecutionResult(
                    toolkits=[],
                    terminal_event_observed=True,
                    no_actionable_work=False,
                    run_id=finalized_run_id,
                    terminal_run_status=AgentRunStatus.FAILED,
                )
            await self.error_reporter.report_user_visible(message.session_id, exc)
            await self._clear_activity_after_failed_message(
                message.session_id,
                reason="user_visible_error",
            )
            return RunExecutionResult(
                toolkits=[],
                terminal_event_observed=False,
                no_actionable_work=False,
            )
        except Exception as exc:
            try:
                finalized_run_id = (
                    await self.run_executor.finalize_unhandled_active_run(
                        message.session_id,
                        exc,
                        owner_generation=self._required_owner_generation(),
                        dispatch_event=self.event_publisher.dispatch_event,
                    )
                )
            except CanonicalExecutionOwnerGenerationStaleError as stale:
                return self._handle_canonical_execution_error(message, stale)
            if finalized_run_id is not None:
                return RunExecutionResult(
                    toolkits=[],
                    terminal_event_observed=True,
                    no_actionable_work=False,
                    run_id=finalized_run_id,
                    terminal_run_status=AgentRunStatus.FAILED,
                )
            await self.error_reporter.report_unhandled(message.session_id, exc)
            await self._clear_activity_after_failed_message(
                message.session_id,
                reason="unhandled_error",
            )
            return RunExecutionResult(
                toolkits=[],
                terminal_event_observed=False,
                no_actionable_work=False,
            )

    def _required_owner_generation(self) -> int:
        """Return the claimed generation for the current Runner."""
        if self.owner_generation is None:
            raise RuntimeError("Session ownership generation was not claimed")
        return self.owner_generation

    def _handle_canonical_execution_error(
        self,
        message: BrokerMessage,
        exc: CanonicalExecutionSnapshotError,
    ) -> RunExecutionResult:
        """Stop stale authority without finalizing or reporting another owner's Run."""
        reload_required = isinstance(
            exc,
            CanonicalExecutionOwnerGenerationStaleError
            | CanonicalExecutionWorkDriftError,
        )
        logger.info(
            "Session execution snapshot rejected",
            extra={
                "session_id": message.session_id,
                "error_type": exc.__class__.__name__,
                "reload_required": reload_required,
            },
        )
        self.runner_shutdown.set()
        if reload_required:
            self.handover_wake_up = SessionWakeUp(session_id=message.session_id)
            self.handover_required = True
        return RunExecutionResult(
            toolkits=[],
            terminal_event_observed=False,
            no_actionable_work=False,
        )

    async def _process_wake_up(self, message: SessionWakeUp) -> RunExecutionResult:
        """Handle command/run/continuation lifecycle for one SessionWakeUp."""
        if self.owner_generation is None:
            raise RuntimeError("Session ownership generation was not claimed")
        self.execution_snapshot = None
        snapshot = await self.execution_snapshot_loader.load(
            message.session_id,
            owner_generation=self.owner_generation,
        )
        self.execution_snapshot = snapshot
        await self.subagent_terminal_result_service.deliver_pending_for_source_session(
            message.session_id,
            repair_source="source_session_reuse",
        )
        self.run_active = True
        try:
            result = await self._run_with_timeout(message, snapshot)
        finally:
            self.run_active = False
            if (
                self.stop_controller.handover_stop_requested
                or self.shutdown_event.is_set()
            ) and not self.stop_controller.user_stop_requested:
                self.handover_wake_up = message
        await self._enqueue_wake_up_after_stop_if_needed(message)
        if self.shutdown_event.is_set():
            self._drain_stop_signals()
        return result
