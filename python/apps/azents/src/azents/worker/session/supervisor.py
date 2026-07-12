"""SessionRunner engine task stop/cancel supervision."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from azents.broker.types import SessionWakeUp
from azents.engine.run.types import (
    SHUTDOWN_CANCEL_MESSAGE,
    USER_STOP_CANCEL_MESSAGE,
    CheckStop,
    PollMessages,
)
from azents.repos.agent_session.data import PendingSessionCommand
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.run.executor import RunExecutor
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.contracts import PrepareToolkits
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.user_stop_finalizer import UserStopFinalizer

logger = logging.getLogger(__name__)

_SHUTDOWN_TIMEOUT = 5.0  # seconds — graceful completion window before handover
_EXPLICIT_STOP_POLL_INTERVAL = 0.5  # seconds — user stop detection interval


class ToolAdmissionBarrier:
    """Order foreground tool admission against TERM shutdown observation."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        """Return whether shutdown has closed foreground admission."""
        return self._closed

    async def run_if_open(self, action: Callable[[], Awaitable[None]]) -> bool:
        """Run an admission transaction while holding the shutdown barrier."""
        async with self._lock:
            if self._closed:
                return False
            await action()
            return True

    async def close(self) -> None:
        """Close admission after any transaction already inside the barrier."""
        async with self._lock:
            self._closed = True


class RunStopController:
    """Manage current run stop lifecycle."""

    def __init__(self) -> None:
        self.active_task: asyncio.Task[RunExecutionResult] | None = None
        self.user_stop_requested_event = asyncio.Event()
        self.handover_stop_requested_event = asyncio.Event()
        self.tool_admission_barrier = ToolAdmissionBarrier()

    def clear_for_next_run(self) -> None:
        """Reset in-memory stop state before next run starts."""
        self.user_stop_requested_event.clear()
        self.handover_stop_requested_event.clear()
        self.tool_admission_barrier = ToolAdmissionBarrier()

    def register_active_task(
        self,
        task: asyncio.Task[RunExecutionResult],
    ) -> None:
        """Register current active engine task handle."""
        self.active_task = task

    def clear_active_task(self, task: asyncio.Task[RunExecutionResult]) -> None:
        """Clear handle when it matches registered active task."""
        if self.active_task is task:
            self.active_task = None

    def request_user_stop(self) -> bool:
        """Record User stop and immediately cancel active task when present."""
        self.user_stop_requested_event.set()
        task = self.active_task
        if task is None or task.done():
            return False
        task.cancel(USER_STOP_CANCEL_MESSAGE)
        return True

    def request_handover_stop(self) -> None:
        """Record Shutdown/handover stop reason."""
        self.handover_stop_requested_event.set()

    @property
    def user_stop_requested(self) -> bool:
        """Return whether User stop was requested."""
        return self.user_stop_requested_event.is_set()

    @property
    def handover_stop_requested(self) -> bool:
        """Return whether Shutdown/handover stop was requested."""
        return self.handover_stop_requested_event.is_set()


class RunTaskSupervisor:
    """Manage stop/shutdown/cancel lifecycle while engine task runs."""

    def __init__(
        self,
        *,
        run_executor: RunExecutor,
        user_stop_finalizer: UserStopFinalizer,
        shutdown_event: asyncio.Event,
        event_publisher: WorkerEventPublisher,
        session_lifecycle: SessionLifecycleService,
        stop_controller: RunStopController,
    ) -> None:
        self.run_executor = run_executor
        self.user_stop_finalizer = user_stop_finalizer
        self.shutdown_event = shutdown_event
        self.event_publisher = event_publisher
        self.session_lifecycle = session_lifecycle
        self.stop_controller = stop_controller

    async def run(
        self,
        message: SessionWakeUp,
        *,
        poll_fn: PollMessages,
        check_stop: CheckStop,
        prepare_toolkits: PrepareToolkits,
        drain_stop_signals: Callable[[], None],
        owner_generation: int,
        command: PendingSessionCommand | None = None,
    ) -> RunExecutionResult:
        """Create engine execution task and apply stop/shutdown policy."""
        engine_task: asyncio.Task[RunExecutionResult] = asyncio.create_task(
            self.run_executor.execute(
                message,
                poll_fn=poll_fn,
                check_stop=check_stop,
                prepare_toolkits=prepare_toolkits,
                shutdown_event=self.shutdown_event,
                dispatch_event=self.event_publisher.dispatch_event,
                owner_generation=owner_generation,
                tool_admission_barrier=self.stop_controller.tool_admission_barrier,
                command=command,
            )
        )
        self.stop_controller.register_active_task(engine_task)

        if self.shutdown_event.is_set():
            self.stop_controller.request_handover_stop()
            await self.stop_controller.tool_admission_barrier.close()
            try:
                return await self._wait_for_shutdown_completion(
                    engine_task,
                    timeout=_SHUTDOWN_TIMEOUT,
                )
            finally:
                self.stop_controller.clear_active_task(engine_task)

        explicit_stop_waiter = asyncio.create_task(
            self._wait_for_explicit_stop(
                message.session_id,
                drain_stop_signals=drain_stop_signals,
            )
        )
        shutdown_waiter = asyncio.create_task(self.shutdown_event.wait())
        try:
            done, _ = await asyncio.wait(
                [engine_task, explicit_stop_waiter, shutdown_waiter],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if engine_task in done:
                if engine_task.cancelled() and self.stop_controller.user_stop_requested:
                    await self.user_stop_finalizer.finalize(
                        message.session_id,
                        run_id=None,
                        active_tool_calls=[],
                    )
                    return RunExecutionResult(
                        toolkits=[],
                        terminal_event_observed=True,
                        no_actionable_work=False,
                    )
                return engine_task.result()
            if explicit_stop_waiter in done:
                logger.info(
                    "Explicit stop detected during engine run, canceling",
                    extra={"session_id": message.session_id},
                )
                await self.user_stop_finalizer.finalize(
                    message.session_id,
                    run_id=None,
                    active_tool_calls=[],
                )
                return await self._cancel_now(engine_task)

            self.stop_controller.request_handover_stop()
            await self.stop_controller.tool_admission_barrier.close()
            logger.info(
                "Shutdown detected during engine run, applying timeout",
                extra={
                    "session_id": message.session_id,
                    "timeout": _SHUTDOWN_TIMEOUT,
                },
            )
            return await self._wait_for_shutdown_completion(
                engine_task,
                timeout=_SHUTDOWN_TIMEOUT,
            )
        finally:
            waiters = [explicit_stop_waiter, shutdown_waiter]
            for waiter in waiters:
                if not waiter.done():
                    waiter.cancel()
            for waiter in waiters:
                with contextlib.suppress(asyncio.CancelledError):
                    await waiter
            self.stop_controller.clear_active_task(engine_task)

    async def _wait_for_explicit_stop(
        self,
        session_id: str,
        *,
        drain_stop_signals: Callable[[], None],
    ) -> None:
        """Detect SessionStopSignal or durable stop intent."""
        while True:
            drain_stop_signals()
            if await self.session_lifecycle.has_stop_request(session_id):
                self.stop_controller.request_user_stop()
            if self.stop_controller.user_stop_requested:
                return
            await asyncio.sleep(_EXPLICIT_STOP_POLL_INTERVAL)

    async def _cancel_now(
        self,
        task: asyncio.Task[RunExecutionResult],
    ) -> RunExecutionResult:
        """Send cancel to engine task on explicit stop and return immediately."""
        task.cancel(USER_STOP_CANCEL_MESSAGE)
        asyncio.create_task(self._observe_cancelled_engine_task(task))
        return RunExecutionResult(
            toolkits=[],
            terminal_event_observed=True,
            no_actionable_work=False,
        )

    async def _observe_cancelled_engine_task(
        self,
        task: asyncio.Task[RunExecutionResult],
    ) -> None:
        """Collect termination result of fire-and-forget engine task."""
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Engine task failed after user stop cancellation")

    async def _wait_for_shutdown_completion(
        self,
        task: asyncio.Task[RunExecutionResult],
        *,
        timeout: float,
    ) -> RunExecutionResult:
        """Wait for graceful shutdown completion before canceling the task."""
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "Engine task timed out after shutdown, canceling",
                extra={"timeout": timeout},
            )
            task.cancel(SHUTDOWN_CANCEL_MESSAGE)
            try:
                await task
            except asyncio.CancelledError:
                # If check_stop is not called within the timeout, run_state stays
                # RUNNING and stale heartbeat recovery takes over.
                pass
            return RunExecutionResult(
                toolkits=[],
                terminal_event_observed=False,
                no_actionable_work=False,
            )
