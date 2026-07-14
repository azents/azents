"""Run task supervisor concurrency tests."""

import asyncio
from collections.abc import Callable, Sequence
from typing import cast

import pytest

import azents.worker.session.supervisor as supervisor_module
from azents.broker.types import PublishedEvent, SessionWakeUp
from azents.core.enums import AgentRunStatus
from azents.engine.events.types import ActiveToolCall
from azents.engine.run.contracts import ToolkitBinding
from azents.engine.run.types import PollMessagesResult
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.run.executor import RunExecutor
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.supervisor import (
    RunStopController,
    RunTaskSupervisor,
    ToolAdmissionBarrier,
)
from azents.worker.session.user_stop_finalizer import UserStopFinalizer


class _RunExecutor:
    """Configurable engine task used by supervisor tests."""

    def __init__(self, mode: str, *, gate: asyncio.Event | None = None) -> None:
        self.mode = mode
        self.gate = gate or asyncio.Event()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()
        self.cancellation_args: list[tuple[object, ...]] = []

    async def execute(
        self,
        message: SessionWakeUp,
        **kwargs: object,
    ) -> RunExecutionResult:
        """Run according to the configured completion/cancellation behavior."""
        del message, kwargs
        self.started.set()
        if self.mode == "complete":
            return _completed_result()
        if self.mode == "gated_complete":
            await self.gate.wait()
            return _completed_result()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as exc:
            self.cancelled.set()
            self.cancellation_args.append(exc.args)
            if self.mode != "swallow":
                raise
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError as exc:
                self.cancellation_args.append(exc.args)
        return _completed_result()


class _SessionLifecycle:
    """Durable stop validation test double."""

    def __init__(
        self,
        *,
        gate: asyncio.Event | None = None,
        has_stop: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.gate = gate
        self.has_stop = has_stop
        self.error = error

    async def has_stop_request(
        self,
        session_id: str,
        *,
        stop_request_id: str | None,
    ) -> bool:
        """Wait for the test gate, then return or raise its durable result."""
        del session_id, stop_request_id
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return self.has_stop


class _UserStopFinalizer:
    """Record terminal user-stop finalization."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.barrier: ToolAdmissionBarrier | None = None
        self.barrier_closed_states: list[bool] = []

    async def finalize(
        self,
        session_id: str,
        *,
        run_id: str | None,
        active_tool_calls: Sequence[ActiveToolCall],
    ) -> str | None:
        """Record one finalization and return its Run id."""
        del active_tool_calls
        self.calls.append((session_id, run_id))
        assert self.barrier is not None
        self.barrier_closed_states.append(self.barrier.closed)
        return run_id


class _EventPublisher:
    """Unused event publisher test double."""

    async def dispatch_event(
        self,
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        """Accept an event without external I/O."""
        del session_id, event


def _completed_result() -> RunExecutionResult:
    return RunExecutionResult(
        toolkits=[],
        terminal_event_observed=True,
        no_actionable_work=False,
        run_id="run-001",
        terminal_run_status=AgentRunStatus.COMPLETED,
    )


def _wake_up() -> SessionWakeUp:
    return SessionWakeUp(
        agent_id="agent-001",
        session_id="session-001",
        user_id="user-001",
        additional_system_prompt=None,
        interface=None,
        workspace_id="workspace-001",
        workspace_handle=None,
    )


def _supervisor(
    executor: _RunExecutor,
    lifecycle: _SessionLifecycle,
    *,
    shutdown_event: asyncio.Event | None = None,
) -> tuple[RunTaskSupervisor, RunStopController, _UserStopFinalizer]:
    controller = RunStopController()
    finalizer = _UserStopFinalizer()
    finalizer.barrier = controller.tool_admission_barrier
    supervisor = RunTaskSupervisor(
        run_executor=cast(RunExecutor, executor),
        user_stop_finalizer=cast(UserStopFinalizer, finalizer),
        shutdown_event=shutdown_event or asyncio.Event(),
        event_publisher=cast(WorkerEventPublisher, _EventPublisher()),
        session_lifecycle=cast(SessionLifecycleService, lifecycle),
        stop_controller=controller,
    )
    return supervisor, controller, finalizer


async def _run(supervisor: RunTaskSupervisor) -> RunExecutionResult:
    async def poll() -> PollMessagesResult:
        return PollMessagesResult(
            user_messages=[],
            context_invalidated=False,
            complete_run=False,
        )

    async def check_stop() -> bool:
        return False

    async def prepare_toolkits(
        current: Sequence[ToolkitBinding],
        workspace_id: str | None,
    ) -> list[ToolkitBinding]:
        del workspace_id
        return list(current)

    return await supervisor.run(
        _wake_up(),
        poll_fn=poll,
        check_stop=check_stop,
        prepare_toolkits=prepare_toolkits,
        drain_stop_signals=lambda: None,
        owner_generation=1,
    )


@pytest.mark.asyncio
async def test_stop_waiter_failure_cancels_engine_and_propagates_error() -> None:
    """A DB polling error is not stop authority and cannot leak the engine task."""
    gate = asyncio.Event()
    executor = _RunExecutor("block")
    lifecycle = _SessionLifecycle(gate=gate, error=RuntimeError("DB unavailable"))
    supervisor, controller, finalizer = _supervisor(executor, lifecycle)
    supervised = asyncio.create_task(_run(supervisor))
    await executor.started.wait()

    gate.set()
    with pytest.raises(RuntimeError, match="DB unavailable"):
        await supervised

    assert executor.cancelled.is_set()
    assert controller.tool_admission_barrier.closed
    assert not controller.user_stop_requested
    assert finalizer.calls == []


@pytest.mark.asyncio
async def test_completed_engine_result_wins_over_secondary_waiter_failure() -> None:
    """A completed engine boundary is not replaced by stop-waiter cleanup errors."""
    executor = _RunExecutor("complete")
    lifecycle = _SessionLifecycle(error=RuntimeError("secondary DB failure"))
    supervisor, _, _ = _supervisor(executor, lifecycle)

    result = await _run(supervisor)

    assert result == _completed_result()


@pytest.mark.asyncio
async def test_external_supervisor_cancellation_cancels_and_drains_engine() -> None:
    """Canceling the supervisor cannot orphan its active engine task."""
    executor = _RunExecutor("block")
    lifecycle = _SessionLifecycle(gate=asyncio.Event())
    supervisor, controller, _ = _supervisor(executor, lifecycle)
    supervised = asyncio.create_task(_run(supervisor))
    await executor.started.wait()

    supervised.cancel()
    with pytest.raises(asyncio.CancelledError):
        await supervised

    assert executor.cancelled.is_set()
    assert controller.tool_admission_barrier.closed
    assert supervisor._quarantined_tasks == set()  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_user_stop_quarantines_task_that_swallows_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancellation-swallowing task cannot hold a terminal Stop boundary open."""
    monkeypatch.setattr(supervisor_module, "_CANCEL_CLEANUP_TIMEOUT", 0.01)
    gate = asyncio.Event()
    executor = _RunExecutor("swallow")
    lifecycle = _SessionLifecycle(gate=gate, has_stop=True)
    supervisor, controller, finalizer = _supervisor(executor, lifecycle)
    supervised = asyncio.create_task(_run(supervisor))
    await executor.started.wait()

    try:
        gate.set()
        result = await asyncio.wait_for(supervised, timeout=1)
        await asyncio.wait_for(
            _wait_until(lambda: len(executor.cancellation_args) >= 2),
            timeout=1,
        )

        assert result.terminal_event_observed
        assert finalizer.calls == [("session-001", None)]
        assert finalizer.barrier_closed_states == [True]
        assert controller.tool_admission_barrier.closed
        assert len(supervisor._quarantined_tasks) == 1  # pyright: ignore[reportPrivateUsage]
    finally:
        executor.release.set()
        await asyncio.wait_for(
            _wait_until(
                lambda: not supervisor._quarantined_tasks  # pyright: ignore[reportPrivateUsage]
            ),
            timeout=1,
        )


@pytest.mark.asyncio
async def test_shutdown_quarantines_task_that_swallows_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutdown uses bounded cancellation cleanup after its graceful window."""
    monkeypatch.setattr(supervisor_module, "_SHUTDOWN_TIMEOUT", 0.01)
    monkeypatch.setattr(supervisor_module, "_CANCEL_CLEANUP_TIMEOUT", 0.01)
    executor = _RunExecutor("swallow")
    lifecycle = _SessionLifecycle(gate=asyncio.Event())
    shutdown_event = asyncio.Event()
    shutdown_event.set()
    supervisor, controller, _ = _supervisor(
        executor,
        lifecycle,
        shutdown_event=shutdown_event,
    )

    try:
        result = await asyncio.wait_for(_run(supervisor), timeout=1)
        await asyncio.wait_for(
            _wait_until(lambda: len(executor.cancellation_args) >= 2),
            timeout=1,
        )

        assert not result.terminal_event_observed
        assert controller.tool_admission_barrier.closed
        assert len(supervisor._quarantined_tasks) == 1  # pyright: ignore[reportPrivateUsage]
    finally:
        executor.release.set()
        await asyncio.wait_for(
            _wait_until(
                lambda: not supervisor._quarantined_tasks  # pyright: ignore[reportPrivateUsage]
            ),
            timeout=1,
        )


async def _wait_until(predicate: Callable[[], bool]) -> None:
    """Yield until a zero-argument predicate becomes true."""
    while not predicate():
        await asyncio.sleep(0)
