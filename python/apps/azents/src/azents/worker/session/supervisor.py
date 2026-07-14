"""SessionRunner engine task stop/cancel supervision."""

import asyncio
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

_SHUTDOWN_TIMEOUT = 30.0  # seconds — foreground completion window before handover
_EXPLICIT_STOP_POLL_INTERVAL = 0.5  # seconds — user stop detection interval
_CANCEL_CLEANUP_TIMEOUT = 1.0  # seconds — bounded drain after task cancellation


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
        self.stop_signal_received_event = asyncio.Event()
        self.handover_stop_requested_event = asyncio.Event()
        self.tool_admission_barrier = ToolAdmissionBarrier()

    def clear_for_next_run(self) -> None:
        """Reset in-memory stop state before next run starts."""
        self.user_stop_requested_event.clear()
        self.stop_signal_received_event.clear()
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
        if self.user_stop_requested_event.is_set():
            return False
        self.user_stop_requested_event.set()
        task = self.active_task
        if task is None or task.done():
            return False
        task.cancel(USER_STOP_CANCEL_MESSAGE)
        return True

    def notify_stop_signal(self) -> None:
        """Wake the supervisor so it can validate durable stop authority."""
        self.stop_signal_received_event.set()

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
        self._quarantined_tasks: set[asyncio.Task[RunExecutionResult]] = set()

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
        explicit_stop_waiter: asyncio.Task[None] | None = None
        shutdown_waiter: asyncio.Task[bool] | None = None
        try:
            if self.shutdown_event.is_set():
                self.stop_controller.request_handover_stop()
                await self.stop_controller.tool_admission_barrier.close()
                return await self._wait_for_shutdown_completion(
                    engine_task,
                    timeout=_SHUTDOWN_TIMEOUT,
                )

            explicit_stop_waiter = asyncio.create_task(
                self._wait_for_explicit_stop(
                    message.session_id,
                    drain_stop_signals=drain_stop_signals,
                )
            )
            shutdown_waiter = asyncio.create_task(self.shutdown_event.wait())
            done, _ = await asyncio.wait(
                [engine_task, explicit_stop_waiter, shutdown_waiter],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if engine_task in done:
                if engine_task.cancelled() and self.stop_controller.user_stop_requested:
                    await self.stop_controller.tool_admission_barrier.close()
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
                result = engine_task.result()
                if self.stop_controller.user_stop_requested:
                    await self.stop_controller.tool_admission_barrier.close()
                    await self.user_stop_finalizer.finalize(
                        message.session_id,
                        run_id=result.run_id,
                        active_tool_calls=[],
                    )
                return result
            if explicit_stop_waiter in done:
                # A completed waiter means User stop only when its durable DB
                # validation returned normally. Never reinterpret a DB failure as
                # stop authority.
                try:
                    explicit_stop_waiter.result()
                except Exception:
                    await self._cancel_for_supervisor_exit(engine_task)
                    raise
                await self.stop_controller.tool_admission_barrier.close()
                logger.info(
                    "Explicit stop detected during engine run, canceling",
                    extra={"session_id": message.session_id},
                )
                try:
                    finalized_run_id = await self.user_stop_finalizer.finalize(
                        message.session_id,
                        run_id=None,
                        active_tool_calls=[],
                    )
                except Exception:
                    # The Session boundary must still outlive engine cancellation
                    # cleanup even when durable stop finalization fails.
                    await self._cancel_now(engine_task)
                    raise
                result = await self._cancel_now(engine_task)
                if result.run_id is not None and result.run_id != finalized_run_id:
                    await self.user_stop_finalizer.finalize(
                        message.session_id,
                        run_id=result.run_id,
                        active_tool_calls=[],
                    )
                return result

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
        except asyncio.CancelledError:
            await self._cancel_for_supervisor_exit(engine_task)
            raise
        finally:
            waiters = [
                waiter
                for waiter in (explicit_stop_waiter, shutdown_waiter)
                if waiter is not None
            ]
            for waiter in waiters:
                if not waiter.done():
                    waiter.cancel()
            for waiter in waiters:
                try:
                    await waiter
                except asyncio.CancelledError:
                    pass
                except Exception:
                    # Waiter cleanup is secondary to the already-selected engine,
                    # stop, shutdown, or supervisor-cancellation outcome.
                    logger.warning(
                        "Run supervisor waiter failed during cleanup",
                        extra={"session_id": message.session_id},
                        exc_info=True,
                    )
            self.stop_controller.clear_active_task(engine_task)

    async def _wait_for_explicit_stop(
        self,
        session_id: str,
        *,
        drain_stop_signals: Callable[[], None],
    ) -> None:
        """Detect SessionStopSignal or durable stop intent."""
        while True:
            self.stop_controller.stop_signal_received_event.clear()
            drain_stop_signals()
            if await self.session_lifecycle.has_stop_request(
                session_id,
                stop_request_id=None,
            ):
                self.stop_controller.request_user_stop()
            if self.stop_controller.user_stop_requested:
                return
            try:
                await asyncio.wait_for(
                    self.stop_controller.stop_signal_received_event.wait(),
                    timeout=_EXPLICIT_STOP_POLL_INTERVAL,
                )
            except TimeoutError:
                pass

    async def _cancel_now(
        self,
        task: asyncio.Task[RunExecutionResult],
    ) -> RunExecutionResult:
        """Cancel the engine task and wait for its durable cancellation handoff."""
        await self.stop_controller.tool_admission_barrier.close()
        if not task.done() and task.cancelling() == 0:
            task.cancel(USER_STOP_CANCEL_MESSAGE)
        completed = await self._wait_for_cancel_cleanup(
            task,
            cancel_message=USER_STOP_CANCEL_MESSAGE,
        )
        if completed:
            try:
                return task.result()
            except asyncio.CancelledError:
                pass
        return RunExecutionResult(
            toolkits=[],
            terminal_event_observed=True,
            no_actionable_work=False,
        )

    async def _cancel_for_supervisor_exit(
        self,
        task: asyncio.Task[RunExecutionResult],
    ) -> None:
        """Fence and boundedly drain an engine task for a non-User exit."""
        await self.stop_controller.tool_admission_barrier.close()
        if not task.done() and task.cancelling() == 0:
            task.cancel(SHUTDOWN_CANCEL_MESSAGE)
        completed = await self._wait_for_cancel_cleanup(
            task,
            cancel_message=SHUTDOWN_CANCEL_MESSAGE,
        )
        if not completed:
            return
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning(
                "Engine task failed while supervisor was exiting",
                exc_info=True,
            )

    async def _wait_for_cancel_cleanup(
        self,
        task: asyncio.Task[RunExecutionResult],
        *,
        cancel_message: str,
    ) -> bool:
        """Wait a hard-bounded grace period, then quarantine a stuck task."""
        if task.done():
            return True
        done, _ = await asyncio.wait({task}, timeout=_CANCEL_CLEANUP_TIMEOUT)
        if task in done:
            return True
        task.cancel(cancel_message)
        self._quarantine_task(task)
        logger.error(
            "Engine task ignored cancellation cleanup deadline; quarantined",
            extra={"timeout": _CANCEL_CLEANUP_TIMEOUT},
        )
        return False

    def _quarantine_task(self, task: asyncio.Task[RunExecutionResult]) -> None:
        """Retain a detached engine task and consume its eventual outcome."""
        self._quarantined_tasks.add(task)
        task.add_done_callback(self._on_quarantined_task_done)

    def _on_quarantined_task_done(
        self,
        task: asyncio.Task[RunExecutionResult],
    ) -> None:
        """Release a quarantined task after retrieving its terminal outcome."""
        self._quarantined_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("Quarantined engine task failed", exc_info=True)

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
            if not task.done() and task.cancelling() == 0:
                task.cancel(SHUTDOWN_CANCEL_MESSAGE)
            completed = await self._wait_for_cancel_cleanup(
                task,
                cancel_message=SHUTDOWN_CANCEL_MESSAGE,
            )
            if completed:
                try:
                    return task.result()
                except asyncio.CancelledError:
                    # If check_stop is not called within the timeout, run_state stays
                    # RUNNING and stale heartbeat recovery takes over.
                    pass
            return RunExecutionResult(
                toolkits=[],
                terminal_event_observed=False,
                no_actionable_work=False,
            )
