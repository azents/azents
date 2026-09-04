"""Bounded Local Job Runtime tests."""

import asyncio
import datetime
import logging
from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import cast

import pytest
from azcommon import di

from azents.job_runtime.local import (
    JobRuntimeClosedError,
    LocalJobHandle,
    LocalJobRuntime,
)
from azents.job_runtime.types import (
    JobExecutionContext,
    JobHandler,
    JobHandlerDefinition,
    JobHandlerRegistry,
    JobOutcomeStatus,
    JobPayload,
    JobRequest,
)


class _ReleaseObservableLock(asyncio.Lock):
    """Signal after a tested critical section releases the lock."""

    def __init__(self) -> None:
        super().__init__()
        self.released = asyncio.Event()

    def release(self) -> None:
        super().release()
        self.released.set()


async def _wait_for_runtime_close_started(
    runtime: LocalJobRuntime,
    lock: _ReleaseObservableLock,
) -> None:
    """Wait until the close critical section records the closed state."""
    while not runtime._closed:  # noqa: SLF001
        lock.released.clear()
        if runtime._closed:  # noqa: SLF001
            return
        await lock.released.wait()


def _request(
    execution_key: str,
    *,
    timeout: float = 1.0,
) -> JobRequest:
    return JobRequest(
        handler_key="test.handler",
        execution_key=execution_key,
        deadline=datetime.datetime.now(datetime.UTC)
        + datetime.timedelta(seconds=timeout),
        payload={"execution_key": execution_key},
    )


def _runtime(
    handler: JobHandler,
    *,
    max_concurrency: int = 2,
    cancellation_grace_seconds: float = 0.1,
    container_factory: Callable[[], di.Container] = di.Container,
    rerun_on_coalesce: bool = False,
) -> LocalJobRuntime:
    return LocalJobRuntime(
        handlers=JobHandlerRegistry(
            (
                JobHandlerDefinition(
                    key="test.handler",
                    handler=handler,
                    rerun_on_coalesce=rerun_on_coalesce,
                ),
            )
        ),
        container_factory=container_factory,
        max_concurrency=max_concurrency,
        cancellation_grace_seconds=cancellation_grace_seconds,
    )


@pytest.mark.asyncio
async def test_submit_coalesces_execution_and_waiter_cancellation_isolated() -> None:
    """One cancelled observer does not cancel the accepted execution."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(_context: JobExecutionContext) -> JobPayload:
        started.set()
        await release.wait()
        return {"completed": True}

    runtime = _runtime(handler)
    first = await runtime.submit(_request("same"))
    second = await runtime.submit(_request("same"))
    await started.wait()

    first_wait = asyncio.create_task(first.wait())
    first_wait.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_wait

    assert isinstance(first, LocalJobHandle)
    assert isinstance(second, LocalJobHandle)
    assert first.task is second.task
    assert runtime.active_count == 1

    release.set()
    outcome = await second.wait()

    assert outcome.status is JobOutcomeStatus.SUCCEEDED
    assert outcome.result == {"completed": True}
    assert runtime.active_count == 0


@pytest.mark.asyncio
async def test_opted_in_handler_reruns_one_coalesced_submission() -> None:
    """A wake submitted during handler exit is consumed by the same tracked task."""
    first_started = asyncio.Event()
    first_release = asyncio.Event()
    second_started = asyncio.Event()
    runs = 0

    async def handler(_context: JobExecutionContext) -> JobPayload:
        nonlocal runs
        runs += 1
        if runs == 1:
            first_started.set()
            await first_release.wait()
        else:
            second_started.set()
        return {"runs": runs}

    runtime = _runtime(handler, rerun_on_coalesce=True)
    first = await runtime.submit(_request("same"))
    await first_started.wait()
    second = await runtime.submit(_request("same"))

    assert isinstance(first, LocalJobHandle)
    assert isinstance(second, LocalJobHandle)
    assert first.task is second.task
    assert runs == 1

    first_release.set()
    outcome = await second.wait()

    assert second_started.is_set()
    assert runs == 2
    assert outcome.status is JobOutcomeStatus.SUCCEEDED
    assert outcome.result == {"runs": 2}
    assert runtime.active_count == 0


@pytest.mark.asyncio
async def test_runtime_enforces_concurrency_bound() -> None:
    """A second execution waits until the bounded slot is available."""
    started: list[str] = []
    first_started = asyncio.Event()
    first_release = asyncio.Event()
    second_started = asyncio.Event()

    async def handler(context: JobExecutionContext) -> JobPayload:
        execution_key = cast(str, context.request.payload["execution_key"])
        started.append(execution_key)
        if execution_key == "first":
            first_started.set()
            await first_release.wait()
        else:
            second_started.set()
        return {"execution_key": execution_key}

    runtime = _runtime(handler, max_concurrency=1)
    first = await runtime.submit(_request("first"))
    second = await runtime.submit(_request("second"))
    await first_started.wait()

    assert started == ["first"]
    assert not second_started.is_set()

    first_release.set()
    first_outcome, second_outcome = await asyncio.gather(first.wait(), second.wait())

    assert started == ["first", "second"]
    assert first_outcome.status is JobOutcomeStatus.SUCCEEDED
    assert second_outcome.status is JobOutcomeStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_deadline_expires_while_waiting_for_concurrency_slot() -> None:
    """Semaphore queue time remains inside the absolute request deadline."""
    first_started = asyncio.Event()
    first_release = asyncio.Event()
    started: list[str] = []

    async def handler(context: JobExecutionContext) -> JobPayload:
        execution_key = cast(str, context.request.payload["execution_key"])
        started.append(execution_key)
        if execution_key == "first":
            first_started.set()
            await first_release.wait()
        return {"execution_key": execution_key}

    runtime = _runtime(handler, max_concurrency=1)
    first = await runtime.submit(_request("first"))
    await first_started.wait()
    queued = await runtime.submit(_request("queued", timeout=0.01))

    queued_outcome = await asyncio.wait_for(queued.wait(), timeout=0.2)

    assert queued_outcome.status is JobOutcomeStatus.TIMED_OUT
    assert started == ["first"]

    first_release.set()
    assert (await first.wait()).status is JobOutcomeStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_deadline_cancels_cooperative_handler(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An absolute deadline returns a safe timeout after handler cancellation."""
    cancelled = asyncio.Event()

    async def handler(_context: JobExecutionContext) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    caplog.set_level(logging.WARNING, logger="azents.job_runtime.local")
    runtime = _runtime(handler)
    handle = await runtime.submit(_request("deadline", timeout=0.01))

    outcome = await handle.wait()

    assert outcome.status is JobOutcomeStatus.TIMED_OUT
    assert outcome.error_code == "TimeoutError"
    assert cancelled.is_set()
    assert runtime.active_count == 0
    assert not [
        record
        for record in caplog.records
        if record.getMessage()
        == "Registered job handler failed during cancellation grace"
    ]


@pytest.mark.asyncio
async def test_deadline_logs_handler_failure_during_cancellation_grace(
    caplog: pytest.LogCaptureFixture,
) -> None:
    started = asyncio.Event()
    untrusted = "s3://private-bucket/job-key?endpoint=internal.example"

    async def handler(_context: JobExecutionContext) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError(untrusted) from None

    caplog.set_level(logging.WARNING, logger="azents.job_runtime.local")
    runtime = _runtime(handler)
    handle = await runtime.submit(_request("grace-failure", timeout=0.1))
    await started.wait()

    outcome = await handle.wait()

    assert outcome.status is JobOutcomeStatus.TIMED_OUT
    assert outcome.error_code == "TimeoutError"
    assert runtime.active_count == 0
    records = [
        record
        for record in caplog.records
        if record.getMessage()
        == "Registered job handler failed during cancellation grace"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.exc_info is not None
    log_fields = vars(record)
    assert log_fields["job_handler_key"] == "test.handler"
    assert log_fields["job_execution_key"] == "grace-failure"
    assert log_fields["failure_kind"] == "RuntimeError"
    formatted = logging.Formatter().format(record)
    assert (
        "RuntimeError: Registered job handler failed during cancellation grace"
        in formatted
    )
    assert untrusted not in formatted


class _TrackedContainer:
    """Task-local container double with observable lifecycle."""

    def __init__(self) -> None:
        self.closed = asyncio.Event()

    async def __aenter__(self) -> "_TrackedContainer":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.closed.set()


class _BlockingEnterContainer(_TrackedContainer):
    """Container whose asynchronous startup never completes on its own."""

    def __init__(self) -> None:
        super().__init__()
        self.enter_cancelled = asyncio.Event()

    async def __aenter__(self) -> "_BlockingEnterContainer":
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.enter_cancelled.set()
            raise
        return self


@pytest.mark.asyncio
async def test_deadline_cancels_task_local_container_startup() -> None:
    """Task-local async container entry cannot outlive the job deadline."""
    handler_started = asyncio.Event()
    container = _BlockingEnterContainer()

    async def handler(_context: JobExecutionContext) -> None:
        handler_started.set()

    runtime = _runtime(
        handler,
        container_factory=cast(
            Callable[[], di.Container],
            lambda: container,
        ),
    )
    handle = await runtime.submit(_request("container-start", timeout=0.01))

    outcome = await asyncio.wait_for(handle.wait(), timeout=0.2)

    assert outcome.status is JobOutcomeStatus.TIMED_OUT
    assert container.enter_cancelled.is_set()
    assert not handler_started.is_set()
    assert runtime.active_count == 0


@pytest.mark.asyncio
async def test_cancellation_grace_overrun_returns_terminal_outcome() -> None:
    """A cancellation-violating handler is quarantined after terminal timeout."""
    cancelled = asyncio.Event()
    release = asyncio.Event()
    container = _TrackedContainer()
    starts = 0

    async def handler(_context: JobExecutionContext) -> None:
        nonlocal starts
        starts += 1
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()

    runtime = _runtime(
        handler,
        max_concurrency=1,
        cancellation_grace_seconds=0.01,
        container_factory=cast(
            Callable[[], di.Container],
            lambda: container,
        ),
    )
    handle = await runtime.submit(_request("overrun", timeout=0.01))
    close_task: asyncio.Task[None] | None = None
    try:
        outcome = await asyncio.wait_for(handle.wait(), timeout=0.2)

        assert outcome.status is JobOutcomeStatus.TIMED_OUT
        assert cancelled.is_set()
        assert not container.closed.is_set()
        assert runtime.active_count == 1
        assert starts == 1

        duplicate = await runtime.submit(_request("overrun"))
        assert isinstance(handle, LocalJobHandle)
        assert isinstance(duplicate, LocalJobHandle)
        assert duplicate.task is handle.task
        assert (await duplicate.wait()).status is JobOutcomeStatus.TIMED_OUT
        assert starts == 1

        blocked = await runtime.submit(_request("blocked", timeout=0.01))
        assert (await asyncio.wait_for(blocked.wait(), timeout=0.2)).status is (
            JobOutcomeStatus.TIMED_OUT
        )
        assert starts == 1

        close_lock = _ReleaseObservableLock()
        runtime._lock = close_lock  # noqa: SLF001  # observe the shutdown boundary under test
        close_task = asyncio.create_task(runtime.close())
        await _wait_for_runtime_close_started(runtime, close_lock)
        assert not close_task.done()
    finally:
        release.set()
        if close_task is None:
            close_task = asyncio.create_task(runtime.close())
        await asyncio.wait_for(close_task, timeout=0.2)
    await asyncio.wait_for(container.closed.wait(), timeout=0.2)
    assert runtime.active_count == 0


@pytest.mark.asyncio
async def test_close_cancellation_preserves_quarantined_ownership() -> None:
    """Cancelled shutdown cannot release resources before a handler settles."""
    release = asyncio.Event()
    container = _TrackedContainer()

    async def handler(_context: JobExecutionContext) -> None:
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue

    runtime = _runtime(
        handler,
        max_concurrency=1,
        cancellation_grace_seconds=0.01,
        container_factory=cast(
            Callable[[], di.Container],
            lambda: container,
        ),
    )
    handle = await runtime.submit(_request("close-cancel", timeout=0.01))
    assert (await asyncio.wait_for(handle.wait(), timeout=0.2)).status is (
        JobOutcomeStatus.TIMED_OUT
    )

    close_lock = _ReleaseObservableLock()
    runtime._lock = close_lock  # noqa: SLF001  # observe the shutdown boundary under test
    close_task = asyncio.create_task(runtime.close())
    try:
        await _wait_for_runtime_close_started(runtime, close_lock)
        close_task.cancel()

        assert close_task.cancelling()
        assert not close_task.done()
        assert not container.closed.is_set()
        assert runtime.active_count == 1
    finally:
        release.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(close_task, timeout=0.2)
    assert container.closed.is_set()
    assert runtime.active_count == 0


@pytest.mark.asyncio
async def test_close_cancellation_tracks_quarantine_created_during_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close refreshes ownership after its cancellation creates quarantine."""
    started = asyncio.Event()
    release = asyncio.Event()
    container = _TrackedContainer()

    async def handler(_context: JobExecutionContext) -> None:
        started.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue

    runtime = _runtime(
        handler,
        max_concurrency=1,
        cancellation_grace_seconds=0.01,
        container_factory=cast(
            Callable[[], di.Container],
            lambda: container,
        ),
    )
    await runtime.submit(_request("dynamic-quarantine", timeout=1.0))
    await started.wait()

    close_lock = _ReleaseObservableLock()
    runtime._lock = close_lock  # noqa: SLF001  # observe the shutdown boundary under test
    cleanup_adopted = asyncio.Event()
    adopt_detached_cleanup = runtime._adopt_detached_cleanup  # noqa: SLF001

    async def observe_cleanup_adoption(
        handler_task: asyncio.Future[JobPayload | None],
        container_stack: AsyncExitStack,
        *,
        request: JobRequest,
    ) -> None:
        await adopt_detached_cleanup(
            handler_task,
            container_stack,
            request=request,
        )
        cleanup_adopted.set()

    monkeypatch.setattr(runtime, "_adopt_detached_cleanup", observe_cleanup_adoption)
    close_task = asyncio.create_task(runtime.close())
    try:
        await _wait_for_runtime_close_started(runtime, close_lock)
        close_task.cancel()
        await cleanup_adopted.wait()

        assert not close_task.done()
        assert not container.closed.is_set()
        assert runtime.active_count == 1
    finally:
        release.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(close_task, timeout=0.2)
    assert container.closed.is_set()
    assert runtime.active_count == 0


@pytest.mark.asyncio
async def test_close_rejects_new_work_and_drains_accepted_task() -> None:
    """Shutdown atomically closes submission before waiting for accepted work."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(_context: JobExecutionContext) -> None:
        started.set()
        await release.wait()

    runtime = _runtime(handler)
    assert runtime.shutdown_drain_seconds is None
    handle = await runtime.submit(_request("accepted"))
    await started.wait()

    close_lock = _ReleaseObservableLock()
    runtime._lock = close_lock  # noqa: SLF001  # observe the shutdown boundary under test
    close_task = asyncio.create_task(runtime.close())
    await _wait_for_runtime_close_started(runtime, close_lock)

    with pytest.raises(JobRuntimeClosedError):
        await runtime.submit(_request("rejected"))

    assert not close_task.done()
    release.set()
    await close_task
    assert (await handle.wait()).status is JobOutcomeStatus.SUCCEEDED
    assert runtime.active_count == 0
    assert runtime.shutdown_drain_seconds is not None
    assert runtime.shutdown_drain_seconds >= 0


@pytest.mark.asyncio
async def test_submit_rejects_unknown_registered_handler() -> None:
    """Requests cannot escape the closed code-owned handler registry."""

    async def handler(_context: JobExecutionContext) -> None:
        return None

    runtime = _runtime(handler)
    request = JobRequest(
        handler_key="unknown",
        execution_key="unknown",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1),
        payload={},
    )

    with pytest.raises(ValueError, match="Unknown registered job handler"):
        await runtime.submit(request)
