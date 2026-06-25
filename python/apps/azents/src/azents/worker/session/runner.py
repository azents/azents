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
    SessionStopSignal,
    SessionWakeUp,
)
from azents.engine.io.user_input import RunUserMessage
from azents.engine.run.contracts import AgentEngineProtocol, ToolkitBinding
from azents.engine.run.errors import UserVisibleRuntimeError
from azents.engine.run.types import CheckStop, PollMessages
from azents.rdb.session import SessionManager
from azents.repos.agent_session.data import PendingSessionCommand
from azents.services.input_buffer import InputBufferService
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.run.command_executor import CommandExecutor
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
    """stale wake-up 뒤에 닫아야 하는 terminal run boundary."""

    message: SessionWakeUp
    toolkits: list[ToolkitBinding]
    run_id: str | None


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
        command_executor: CommandExecutor,
        engine: AgentEngineProtocol,
    ) -> None:
        self.shutdown_event = shutdown_event
        self.event_publisher = event_publisher
        self.session_lifecycle = session_lifecycle
        self.session_manager = session_manager
        self.agent_session_repository = agent_session_repository
        self.input_buffer_service = input_buffer_service
        self.idle_continuation_service = idle_continuation_service
        self.command_executor = command_executor
        self.inbox = SessionRunnerInbox()
        self.runner_shutdown = asyncio.Event()
        self.terminated_event = asyncio.Event()
        self.started = False
        self.stop_controller = RunStopController()
        self.current_session_id: str | None = None
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
        self.pending_idle_boundary: _PendingIdleBoundary | None = None

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
        user_id: str | None,
    ) -> list[ToolkitBinding]:
        """Prepare Session-managed toolkit snapshot."""
        return await self.toolkit_scope.prepare(toolkits, user_id)

    def _make_poll_fn(self) -> PollMessages:
        """Create poll_messages callback to inject into engine.run()."""

        async def poll() -> list[RunUserMessage]:
            self._drain_stop_signals()
            return []

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

            if await self.session_lifecycle.has_stop_request(session_id):
                self.stop_controller.request_user_stop()
                return True

            if self.shutdown_event.is_set():
                self.stop_controller.request_handover_stop()
                return True

            return False

        return check_stop

    async def _run_with_timeout(
        self,
        message: SessionWakeUp,
    ) -> RunExecutionResult:
        """Delegate engine execution to stop/shutdown supervisor."""
        return await self.run_supervisor.run(
            message,
            poll_fn=self._make_poll_fn(),
            check_stop=self._make_check_stop_fn(message.session_id),
            prepare_toolkits=self.prepare_toolkits,
            drain_stop_signals=self._drain_stop_signals,
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

    async def _mark_idle_after_boundary(
        self,
        boundary: _PendingIdleBoundary,
    ) -> bool:
        """terminal boundary 를 idle transition 과 idle hook 으로 닫는다."""
        logger.info(
            "Session runner marking session idle after terminal run",
            extra={"session_id": boundary.message.session_id},
        )
        marked_idle = await self.session_lifecycle.mark_session_idle(
            boundary.message.session_id
        )
        if not marked_idle:
            return False
        await self.session_lifecycle.clear_session_activity(boundary.message.session_id)
        await self.idle_continuation_service.enqueue(
            boundary.message,
            toolkits=boundary.toolkits,
            run_id=boundary.run_id,
        )
        return True

    async def _release_current_session(self) -> None:
        """Release current session ownership or hand it over to another worker."""
        session_id = self.current_session_id
        if session_id is None:
            return

        wake_up = self.handover_wake_up
        if wake_up is None:
            await self.session_lifecycle.release_session_lock(session_id)
            return

        should_handover = await self.session_lifecycle.has_running_agent_run(
            session_id,
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

    async def _loop(self) -> None:
        """Session message processing loop."""
        idle_started_at = asyncio.get_running_loop().time()
        try:
            while await self._tick(idle_started_at):
                pass
        finally:
            toolkit_cleanup_error: Exception | None = None
            try:
                await self.toolkit_scope.cleanup()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                toolkit_cleanup_error = exc
            if self.current_session_id is not None:
                logger.info(
                    "Session runner stopped, releasing lock",
                    extra={"session_id": self.current_session_id},
                )
                await self._release_current_session()
            if toolkit_cleanup_error is not None:
                raise toolkit_cleanup_error

    async def _tick(self, idle_started_at: float) -> bool:
        wait_result = await self.waiter.wait_next(
            inbox=self.inbox,
            runner_shutdown=self.runner_shutdown,
            current_session_id=self.current_session_id,
            idle_started_at=idle_started_at,
        )
        match wait_result:
            case HeartbeatResult():
                assert self.current_session_id is not None
                await self.session_lifecycle.renew_session_owner_heartbeat(
                    self.current_session_id
                )
                return True
            case IdleTimeoutResult():
                logger.info(
                    "Session runner idle timeout",
                    extra={"session_id": self.current_session_id},
                )
                return False
            case ShutdownResult():
                return False
            case MessageResult(message):
                self.current_session_id = message.session_id
                self.stop_controller.clear_for_next_run()
                self.handover_wake_up = None
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
                        )
                        if await self._has_follow_up_work(message.session_id):
                            self.pending_idle_boundary = boundary
                        else:
                            marked_idle = await self._mark_idle_after_boundary(boundary)
                            self.pending_idle_boundary = None
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
        except UserVisibleRuntimeError as exc:
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
        command_result = await self._process_pending_command(message)
        if command_result is not None:
            return command_result
        self.run_active = True
        try:
            result = await self._run_with_timeout(message)
        finally:
            self.run_active = False
            if (
                self.stop_controller.handover_stop_requested
                and not self.stop_controller.user_stop_requested
            ):
                self.handover_wake_up = message
        await self._enqueue_wake_up_after_stop_if_needed(message)
        if self.shutdown_event.is_set():
            self._drain_stop_signals()
        return result

    async def _process_pending_command(
        self,
        message: SessionWakeUp,
    ) -> RunExecutionResult | None:
        """Consume wake-up through command path when pending command exists."""
        async with self.session_manager() as db_session:
            command = (
                await self.agent_session_repository.get_pending_command_by_session_id(
                    db_session,
                    message.session_id,
                )
            )
        if command is None:
            return None
        return await self.command_executor.execute(
            agent_id=message.agent_id,
            session_id=message.session_id,
            command=command,
            dispatch_event=self.event_publisher.dispatch_event,
        )
