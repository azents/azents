"""SessionRunner engine task stop/cancel supervision."""

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable

from azents.engine.run.model_transport import ModelTransportState
from azents.engine.run.task_supervision import (
    EXPLICIT_STOP_POLL_INTERVAL,
    SHUTDOWN_COMPLETION_TIMEOUT,
    ExecutionTaskSupervision,
)
from azents.engine.run.types import (
    SHUTDOWN_CANCEL_MESSAGE,
    USER_STOP_CANCEL_MESSAGE,
    CheckStop,
    PollMessages,
)
from azents.repos.session_execution.data import CanonicalExecutionSnapshot
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.run.executor import RunExecutor
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.contracts import PrepareToolkits
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.mailbox_activity import MailboxActivityObserver
from azents.worker.session.user_stop_finalizer import UserStopFinalizer

logger = logging.getLogger(__name__)

_SHUTDOWN_TIMEOUT = SHUTDOWN_COMPLETION_TIMEOUT


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
        if self.user_stop_requested_event.is_set():
            return False
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
        snapshot: CanonicalExecutionSnapshot,
        *,
        poll_fn: PollMessages,
        check_stop: CheckStop,
        prepare_toolkits: PrepareToolkits,
        drain_stop_signals: Callable[[], None],
        model_transport_state: ModelTransportState,
        mailbox_activity_observer: MailboxActivityObserver,
    ) -> RunExecutionResult:
        """Create engine execution task and apply stop/shutdown policy."""
        engine_task: asyncio.Task[RunExecutionResult] = asyncio.create_task(
            self.run_executor.execute(
                snapshot,
                poll_fn=poll_fn,
                check_stop=check_stop,
                prepare_toolkits=prepare_toolkits,
                shutdown_event=self.shutdown_event,
                dispatch_event=functools.partial(
                    self.event_publisher.dispatch_event,
                    owner_generation=snapshot.owner_generation,
                ),
                owner_generation=snapshot.owner_generation,
                tool_admission_barrier=self.stop_controller.tool_admission_barrier,
                model_transport_state=model_transport_state,
                mailbox_activity_observer=mailbox_activity_observer,
            )
        )
        self.stop_controller.register_active_task(engine_task)

        async def wait_for_stop() -> None:
            await self._wait_for_explicit_stop(
                snapshot.session_id,
                drain_stop_signals=drain_stop_signals,
            )

        async def finalize_stop() -> None:
            await self.user_stop_finalizer.finalize(
                snapshot.session_id,
                owner_generation=snapshot.owner_generation,
                run_id=None,
                active_tool_calls=[],
            )

        def cancelled_result(terminal: bool) -> RunExecutionResult:
            return RunExecutionResult(
                toolkits=[],
                terminal_event_observed=terminal,
                no_actionable_work=False,
            )

        supervision = ExecutionTaskSupervision(
            session_id=snapshot.session_id,
            shutdown_event=self.shutdown_event,
            wait_for_explicit_stop=wait_for_stop,
            finalize_explicit_stop=finalize_stop,
            user_stop_requested=lambda: self.stop_controller.user_stop_requested,
            request_handover_stop=self.stop_controller.request_handover_stop,
            close_tool_admission=self.stop_controller.tool_admission_barrier.close,
            cancelled_result=cancelled_result,
            shutdown_timeout=_SHUTDOWN_TIMEOUT,
            user_stop_cancel_message=USER_STOP_CANCEL_MESSAGE,
            shutdown_cancel_message=SHUTDOWN_CANCEL_MESSAGE,
        )
        try:
            return await supervision.run(engine_task)
        finally:
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
            await asyncio.sleep(EXPLICIT_STOP_POLL_INTERVAL)
