"""Per-session worker runner orchestration."""

import asyncio
import dataclasses
import logging
from collections.abc import Sequence
from typing import Protocol, assert_never

from azcommon.logging import bind_extra
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import (
    BrokerMessage,
    SessionOwnershipLostError,
    SessionStopSignal,
    SessionWakeUp,
)
from azents.core.enums import AgentRunStatus
from azents.engine.run.contracts import AgentEngineProtocol, ToolkitBinding
from azents.engine.run.errors import UserVisibleRuntimeError
from azents.engine.run.types import CheckStop, PollMessages, PollMessagesResult
from azents.rdb.session import SessionManager
from azents.repos.agent_session.data import PendingSessionCommand
from azents.services.input_buffer import InputBufferService
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.run.executor import RunExecutor
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.errors import SessionRunnerErrorReporter
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


class AgentSessionCommandReader(Protocol):
    """Read pending commands for a session runner."""

    async def get_pending_command_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> PendingSessionCommand | None:
        """Fetch a pending command for a session."""
        ...


@dataclasses.dataclass(frozen=True)
class _PendingIdleBoundary:
    """Terminal run boundary deferred until stale wake-ups are drained."""

    message: SessionWakeUp
    toolkits: list[ToolkitBinding]
    run_id: str | None
    run_status: AgentRunStatus | None


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
        session_manager: SessionManager[AsyncSession],
        agent_session_repository: AgentSessionCommandReader,
        input_buffer_service: InputBufferService,
        idle_continuation_service: IdleContinuationService,
        user_stop_finalizer: UserStopFinalizer,
        run_executor: RunExecutor,
        engine: AgentEngineProtocol,
    ) -> None:
        self.shutdown_event = shutdown_event
        self.event_publisher = event_publisher
        self.session_lifecycle = session_lifecycle
        self.session_manager = session_manager
        self.agent_session_repository = agent_session_repository
        self.input_buffer_service = input_buffer_service
        self.idle_continuation_service = idle_continuation_service
        self.user_stop_finalizer = user_stop_finalizer
        self.run_executor = run_executor
        self.inbox = SessionRunnerInbox()
        self.runner_shutdown = asyncio.Event()
        self.terminated_event = asyncio.Event()
        self.started = False
        self.stop_controller = RunStopController()
        self.running_session_id: str | None = None
        self.owner_generation: int | None = None
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
        self.in_flight_message: BrokerMessage | None = None
        self._accepting_messages = True
        self.pending_idle_boundary: _PendingIdleBoundary | None = None

    @property
    def terminated(self) -> bool:
        """Whether Runner loop has ended."""
        return self.terminated_event.is_set()

    @property
    def accepting_messages(self) -> bool:
        """Whether the Runner can safely accept another local broker delivery."""
        return self._accepting_messages

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
        if not self._accepting_messages:
            raise RuntimeError("Session runner no longer accepts messages")
        self.inbox.enqueue(message, stop_controller=self.stop_controller)

    async def prepare_toolkits(
        self,
        toolkits: Sequence[ToolkitBinding],
        user_id: str | None,
    ) -> list[ToolkitBinding]:
        """Prepare Session-managed toolkit snapshot."""
        return await self.toolkit_scope.prepare(toolkits, user_id)

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
        has_pending = self.input_buffer_service.has_pending_session_input_buffers
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

            if await self.session_lifecycle.has_stop_request(
                session_id,
                stop_request_id=None,
            ):
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
        *,
        command: PendingSessionCommand | None = None,
    ) -> RunExecutionResult:
        """Delegate engine execution to stop/shutdown supervisor."""
        if self.owner_generation is None:
            raise RuntimeError("Session ownership generation was not claimed")
        return await self.run_supervisor.run(
            message,
            poll_fn=self._make_poll_fn(),
            check_stop=self._make_check_stop_fn(message.session_id),
            prepare_toolkits=self.prepare_toolkits,
            drain_stop_signals=self._drain_stop_signals,
            owner_generation=self.owner_generation,
            command=command,
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
        has_pending_input = self.input_buffer_service.has_pending_session_input_buffers
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
        marked_idle = await self.session_lifecycle.mark_session_idle(session_id)
        if not marked_idle:
            return False
        await self.session_lifecycle.clear_session_activity(session_id)
        return True

    async def _mark_idle_after_standalone_stop(self, session_id: str) -> bool:
        """Close a durable stop consumed without an active engine task."""
        logger.info(
            "Session runner marking session idle after standalone stop",
            extra={"session_id": session_id},
        )
        marked_idle = await self.session_lifecycle.mark_session_idle(session_id)
        if not marked_idle:
            return False
        await self.session_lifecycle.clear_session_activity(session_id)
        return True

    async def _mark_idle_after_boundary(
        self,
        boundary: _PendingIdleBoundary,
        *,
        enqueue_idle_continuation: bool = True,
    ) -> bool:
        """Close a terminal boundary through idle transition and idle hook."""
        logger.info(
            "Session runner marking session idle after terminal run",
            extra={
                "session_id": boundary.message.session_id,
                "run_status": boundary.run_status,
            },
        )
        marked_idle = await self.session_lifecycle.mark_session_idle(
            boundary.message.session_id
        )
        if not marked_idle:
            return False
        await self.session_lifecycle.clear_session_activity(boundary.message.session_id)
        if (
            boundary.run_status == AgentRunStatus.COMPLETED
            and enqueue_idle_continuation
        ):
            await self.idle_continuation_service.enqueue(
                boundary.message,
                toolkits=boundary.toolkits,
                run_id=boundary.run_id,
            )
        elif boundary.run_status != AgentRunStatus.COMPLETED:
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
        """Release current session ownership."""
        session_id = self.running_session_id
        if session_id is None:
            return
        await self.session_lifecycle.release_session_lock(session_id)

    async def _redeliver_unacknowledged_messages(self) -> None:
        """Return in-flight and locally queued hints to the durable broker queue."""
        messages = self.inbox.drain()
        if self.in_flight_message is not None:
            messages.insert(0, self.in_flight_message)
        self.in_flight_message = None
        if not messages:
            return

        logger.info(
            "Session runner redelivering unacknowledged broker messages",
            extra={
                "session_id": messages[0].session_id,
                "message_count": len(messages),
            },
        )
        for message in messages:
            try:
                match message:
                    case SessionWakeUp():
                        await self.session_lifecycle.send_session_wake_up(message)
                    case SessionStopSignal():
                        await self.session_lifecycle.send_session_message(message)
                    case _:
                        assert_never(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                # All broker envelopes are hints for durable input, command, or stop
                # state. The stuck-session scanner remains the final recovery path.
                logger.exception(
                    "Failed to redeliver unacknowledged broker message",
                    extra={
                        "session_id": message.session_id,
                        "message_type": type(message).__name__,
                    },
                )

    async def _loop(self) -> None:
        """Session message processing loop."""
        idle_started_at = asyncio.get_running_loop().time()
        try:
            while await self._tick(idle_started_at):
                pass
        finally:
            try:
                if self.running_session_id is not None:
                    logger.info(
                        "Session runner stopped, releasing lock",
                        extra={"session_id": self.running_session_id},
                    )
                    await self._release_current_session()
            finally:
                # Keep accepting direct-stream deliveries until the release await
                # finishes. They are then drained with the current in-flight hint.
                self._accepting_messages = False
                await self._redeliver_unacknowledged_messages()
                # Toolkit cleanup can perform external calls. Ownership and broker
                # handoff must already be complete before it can delay or fail.
                await self.toolkit_scope.cleanup()

    async def _tick(self, idle_started_at: float) -> bool:
        wait_result = await self.waiter.wait_next(
            inbox=self.inbox,
            runner_shutdown=self.runner_shutdown,
            running_session_id=self.running_session_id,
            idle_started_at=idle_started_at,
        )
        match wait_result:
            case HeartbeatResult():
                assert self.running_session_id is not None
                await self.session_lifecycle.renew_session_owner_heartbeat(
                    self.running_session_id
                )
                return True
            case IdleTimeoutResult():
                logger.info(
                    "Session runner idle timeout",
                    extra={"session_id": self.running_session_id},
                )
                return False
            case ShutdownResult():
                return False
            case MessageResult(message):
                self.in_flight_message = message
                if self.running_session_id is None:
                    self.running_session_id = message.session_id
                    self.owner_generation = (
                        await self.session_lifecycle.claim_owner_generation(
                            message.session_id
                        )
                    )
                elif self.running_session_id != message.session_id:
                    raise RuntimeError(
                        "Session runner received a cross-session message"
                    )
                self.stop_controller.clear_for_next_run()
                loop = asyncio.get_running_loop()
                message_started_at = loop.time()
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
                            message_started_at - idle_started_at,
                            3,
                        ),
                        "inbox_size": self.inbox.qsize(),
                    },
                )

                result = await self._process_message(message)

                if self.shutdown_event.is_set():
                    return False

                marked_idle = False
                if result.terminal_event_observed:
                    if isinstance(message, SessionWakeUp):
                        boundary = _PendingIdleBoundary(
                            message=message,
                            toolkits=result.toolkits,
                            run_id=result.run_id,
                            run_status=result.terminal_run_status,
                        )
                        if await self._has_follow_up_work(message.session_id):
                            self.pending_idle_boundary = boundary
                        else:
                            marked_idle = await self._mark_idle_after_boundary(boundary)
                            self.pending_idle_boundary = None
                    elif isinstance(message, SessionStopSignal):
                        marked_idle = await self._mark_idle_after_standalone_stop(
                            message.session_id
                        )
                elif result.no_actionable_work and isinstance(message, SessionWakeUp):
                    boundary = self.pending_idle_boundary
                    if (
                        boundary is not None
                        and boundary.message.session_id == message.session_id
                        and not await self._has_follow_up_work(message.session_id)
                    ):
                        marked_idle = await self._mark_idle_after_boundary(boundary)
                        if marked_idle:
                            self.pending_idle_boundary = None
                    elif boundary is None and not await self._has_follow_up_work(
                        message.session_id
                    ):
                        marked_idle = await self._mark_idle_after_no_actionable_wake_up(
                            message.session_id
                        )
                elif result.no_actionable_work and isinstance(
                    message, SessionStopSignal
                ):
                    # The engine may consume and finalize durable intent before its
                    # broker hint is dequeued. Let that now-stale hint close the
                    # pending terminal boundary instead of stranding RUNNING state.
                    boundary = self.pending_idle_boundary
                    if (
                        boundary is not None
                        and boundary.message.session_id == message.session_id
                        and not await self._has_follow_up_work(message.session_id)
                    ):
                        marked_idle = await self._mark_idle_after_boundary(
                            boundary,
                            enqueue_idle_continuation=False,
                        )
                        if marked_idle:
                            self.pending_idle_boundary = None
                    elif boundary is None and not await self._has_follow_up_work(
                        message.session_id
                    ):
                        marked_idle = await self._mark_idle_after_standalone_stop(
                            message.session_id
                        )
                elif (
                    isinstance(message, SessionWakeUp)
                    and self.pending_idle_boundary is not None
                    and self.pending_idle_boundary.message.session_id
                    == message.session_id
                ):
                    self.pending_idle_boundary = None
                L.info(
                    "Session runner wake-up processed",
                    extra={
                        "duration_seconds": round(
                            loop.time() - message_started_at,
                            3,
                        ),
                        "inbox_size": self.inbox.qsize(),
                        "user_stop_requested": self.stop_controller.user_stop_requested,
                        "runner_shutdown": self.runner_shutdown.is_set(),
                        "marked_idle": marked_idle,
                    },
                )

                self.in_flight_message = None
                if self.runner_shutdown.is_set() and self.inbox.empty():
                    return False
                idle_started_at = asyncio.get_running_loop().time()
                return True
            case _:
                assert_never(wait_result)

    async def _process_message(self, message: BrokerMessage) -> RunExecutionResult:
        """Handle one Broker message."""
        try:
            match message:
                case SessionStopSignal():
                    if not await self.session_lifecycle.has_stop_request(
                        message.session_id,
                        # Broker delivery is only a wake hint. Process whichever
                        # stop intent is currently durable so an overwritten
                        # request ID cannot strand the newer stop.
                        stop_request_id=None,
                    ):
                        return RunExecutionResult(
                            toolkits=[],
                            terminal_event_observed=False,
                            no_actionable_work=True,
                        )
                    await self.user_stop_finalizer.finalize(
                        message.session_id,
                        run_id=None,
                        active_tool_calls=[],
                    )
                    return RunExecutionResult(
                        toolkits=[],
                        terminal_event_observed=True,
                        no_actionable_work=False,
                        terminal_run_status=AgentRunStatus.STOPPED,
                    )
                case SessionWakeUp():
                    return await self._process_wake_up(message)
                case _:
                    assert_never(message)
        except asyncio.CancelledError:
            raise
        except SessionOwnershipLostError:
            # A stale owner must leave through lock-release cleanup only. Error
            # reporting or failed-run finalization would let it mutate the Run
            # now owned by another worker.
            raise
        except UserVisibleRuntimeError as exc:
            finalized_run_id = await self.run_executor.finalize_unhandled_active_run(
                message.session_id,
                exc,
                dispatch_event=self.event_publisher.dispatch_event,
            )
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
            finalized_run_id = await self.run_executor.finalize_unhandled_active_run(
                message.session_id,
                exc,
                dispatch_event=self.event_publisher.dispatch_event,
            )
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

    async def _process_wake_up(self, message: SessionWakeUp) -> RunExecutionResult:
        """Handle command/run/continuation lifecycle for one SessionWakeUp."""
        command = await self._get_pending_command(message.session_id)
        self.run_active = True
        try:
            result = await self._run_with_timeout(message, command=command)
        finally:
            self.run_active = False
        await self._enqueue_wake_up_after_stop_if_needed(message)
        if self.shutdown_event.is_set():
            self._drain_stop_signals()
        return result

    async def _get_pending_command(
        self,
        session_id: str,
    ) -> PendingSessionCommand | None:
        """Fetch pending runtime command, if one exists."""
        async with self.session_manager() as db_session:
            return (
                await self.agent_session_repository.get_pending_command_by_session_id(
                    db_session,
                    session_id,
                )
            )
