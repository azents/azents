"""Bounded Local Job Runtime tests."""

import asyncio
import datetime
import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from types import TracebackType

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
        execution_key = context.request.payload["execution_key"]
        assert isinstance(execution_key, str)
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
        execution_key = context.request.payload["execution_key"]
        assert isinstance(execution_key, str)
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
    terminal_records = [
        record
        for record in caplog.records
        if record.name == "azents.job_runtime.local" and record.levelno == logging.ERROR
    ]
    assert len(terminal_records) == 1
    assert terminal_records[0].exc_info is not None
    formatted = logging.Formatter().format(terminal_records[0])
    assert "Traceback (most recent call last)" in formatted
    assert "in handler" in formatted
    assert "Registered job handler exceeded its absolute deadline" in formatted
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
    assert (
        len(
            [
                record
                for record in caplog.records
                if record.name == "azents.job_runtime.local"
                and record.levelno == logging.ERROR
            ]
        )
        == 1
    )


class _TrackedContainer(di.Container):
    """Task-local container double with observable lifecycle."""

    def __init__(self) -> None:
        super().__init__()
        self.closed = asyncio.Event()

    async def __aenter__(self) -> "_TrackedContainer":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        tb: TracebackType | None = None,
    ) -> None:
        await super().__aexit__(exc_type, exc, tb)
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
        container_factory=lambda: container,
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
        container_factory=lambda: container,
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
        container_factory=lambda: container,
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
        container_factory=lambda: container,
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
        handler_semaphore: asyncio.Semaphore | None,
    ) -> None:
        await adopt_detached_cleanup(
            handler_task,
            container_stack,
            request=request,
            handler_semaphore=handler_semaphore,
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


@pytest.mark.asyncio
async def test_handler_failure_logs_one_sanitized_origin_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Terminal ERROR retains origin frames without provider text or context."""
    sensitive = "token=provider-secret response-body-marker"
    context_sensitive = "password=context-secret"
    note_sensitive = "provider-note-marker"

    async def provider_origin() -> None:
        try:
            raise ValueError(context_sensitive)
        except ValueError as cause:
            error = RuntimeError(sensitive)
            error.add_note(note_sensitive)
            raise error from cause

    async def handler(_context: JobExecutionContext) -> None:
        await provider_origin()

    caplog.set_level(logging.WARNING, logger="azents.job_runtime.local")
    runtime = _runtime(handler)
    outcome = await (await runtime.submit(_request("provider-failure"))).wait()

    assert outcome.status is JobOutcomeStatus.FAILED
    records = [
        record
        for record in caplog.records
        if record.name == "azents.job_runtime.local" and record.levelno == logging.ERROR
    ]
    assert len(records) == 1
    record = records[0]
    assert record.exc_info is not None
    assert vars(record)["job_execution_key"] == "provider-failure"
    formatted = logging.Formatter().format(record)
    assert "in provider_origin" in formatted
    assert "RuntimeError: Registered job handler failed" in formatted
    assert sensitive not in formatted
    assert context_sensitive not in formatted
    assert note_sensitive not in formatted


@pytest.mark.asyncio
async def test_runtime_timeout_wins_supervisor_deadline_and_logs_origin(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Runtime-first cancellation still emits one terminal ERROR with origin."""
    supervisor_cutoff = asyncio.Event()
    sensitive = "token=supervisor-provider-marker"

    async def handler(context: JobExecutionContext) -> None:
        remaining = (
            context.request.deadline - datetime.datetime.now(datetime.UTC)
        ).total_seconds()
        try:
            async with asyncio.timeout(remaining):
                await asyncio.Event().wait()
        except TimeoutError:
            supervisor_cutoff.set()
            try:
                raise RuntimeError(sensitive)
            except RuntimeError:
                # Runtime must own the terminal while supervisor cleanup is pending.
                await asyncio.Event().wait()

    caplog.set_level(logging.WARNING, logger="azents.job_runtime.local")
    runtime = _runtime(handler)
    handle = await runtime.submit(_request("deadline-race", timeout=0.02))
    outcome = await handle.wait()

    assert outcome.status is JobOutcomeStatus.TIMED_OUT
    records = [
        record
        for record in caplog.records
        if record.name == "azents.job_runtime.local" and record.levelno == logging.ERROR
    ]
    assert len(records) == 1
    formatted = logging.Formatter().format(records[0])
    assert "in handler" in formatted
    assert "Registered job handler exceeded its absolute deadline" in formatted
    assert sensitive not in formatted


class _FailingLifecycleContainer(_TrackedContainer):
    """Raise untrusted lifecycle errors from observable container origin frames."""

    def __init__(self, *, fail_enter: bool) -> None:
        super().__init__()
        self.fail_enter = fail_enter
        self.sensitive = "token=container-provider-marker"

    async def __aenter__(self) -> "_FailingLifecycleContainer":
        if self.fail_enter:
            raise RuntimeError(self.sensitive)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        tb: TracebackType | None = None,
    ) -> None:
        await super().__aexit__(exc_type, exc, tb)
        raise RuntimeError(self.sensitive)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_enter", [True, False])
async def test_container_failure_logs_one_sanitized_terminal_error(
    caplog: pytest.LogCaptureFixture,
    fail_enter: bool,
) -> None:
    """Container startup and cleanup escapes have one content-safe ERROR."""
    container = _FailingLifecycleContainer(fail_enter=fail_enter)

    async def handler(_context: JobExecutionContext) -> None:
        return None

    caplog.set_level(logging.WARNING, logger="azents.job_runtime.local")
    runtime = _runtime(handler, container_factory=lambda: container)
    outcome = await (await runtime.submit(_request("container-failure"))).wait()

    assert outcome.status is JobOutcomeStatus.FAILED
    assert runtime.active_count == 0
    records = [
        record
        for record in caplog.records
        if record.name == "azents.job_runtime.local" and record.levelno == logging.ERROR
    ]
    assert len(records) == 1
    formatted = logging.Formatter().format(records[0])
    assert ("in __aenter__" if fail_enter else "in __aexit__") in formatted
    assert container.sensitive not in formatted


@pytest.mark.asyncio
async def test_terminal_failure_cleanup_is_sanitized_without_duplicate_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A primary failure owns ERROR even when subsequent cleanup also fails."""
    container = _FailingLifecycleContainer(fail_enter=False)
    sensitive = "password=primary-provider-marker"

    async def handler(_context: JobExecutionContext) -> None:
        raise ValueError(sensitive)

    caplog.set_level(logging.WARNING, logger="azents.job_runtime.local")
    runtime = _runtime(handler, container_factory=lambda: container)
    outcome = await (await runtime.submit(_request("cleanup-after-failure"))).wait()

    assert outcome.status is JobOutcomeStatus.FAILED
    assert outcome.error_code == "ValueError"
    records = [
        record for record in caplog.records if record.name == "azents.job_runtime.local"
    ]
    assert sum(record.levelno == logging.ERROR for record in records) == 1
    assert any(record.levelno == logging.WARNING for record in records)
    formatted = "\n".join(logging.Formatter().format(record) for record in records)
    assert sensitive not in formatted
    assert container.sensitive not in formatted


@pytest.mark.asyncio
async def test_detached_failures_do_not_duplicate_terminal_timeout_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Late handler and cleanup faults are sanitized warnings after one cutoff."""
    release = asyncio.Event()
    container = _FailingLifecycleContainer(fail_enter=False)
    sensitive = "authorization=detached-provider-marker"

    async def handler(_context: JobExecutionContext) -> None:
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue
        raise RuntimeError(sensitive)

    caplog.set_level(logging.WARNING, logger="azents.job_runtime.local")
    runtime = _runtime(
        handler,
        container_factory=lambda: container,
        cancellation_grace_seconds=0.01,
    )
    handle = await runtime.submit(_request("detached-failure", timeout=0.01))
    try:
        assert (await handle.wait()).status is JobOutcomeStatus.TIMED_OUT
    finally:
        release.set()
        await runtime.close()

    records = [
        record for record in caplog.records if record.name == "azents.job_runtime.local"
    ]
    assert sum(record.levelno == logging.ERROR for record in records) == 1
    assert any(
        record.getMessage() == "Detached registered job cleanup failed"
        for record in records
    )
    formatted = "\n".join(logging.Formatter().format(record) for record in records)
    assert "in timeout" in formatted
    assert sensitive not in formatted
    assert container.sensitive not in formatted
    assert runtime.active_count == 0


@pytest.mark.asyncio
async def test_synchronous_handler_startup_error_survives_cleanup_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The handler factory's primary origin wins a failing container teardown."""
    container = _FailingLifecycleContainer(fail_enter=False)
    sensitive = "password=synchronous-startup-marker"

    def handler(_context: JobExecutionContext) -> Awaitable[JobPayload | None]:
        raise ValueError(sensitive)

    caplog.set_level(logging.WARNING, logger="azents.job_runtime.local")
    runtime = _runtime(handler, container_factory=lambda: container)
    outcome = await (await runtime.submit(_request("sync-startup"))).wait()
    assert outcome.status is JobOutcomeStatus.FAILED
    assert outcome.error_code == "ValueError" and runtime.active_count == 0
    records = [
        record for record in caplog.records if record.name == "azents.job_runtime.local"
    ]
    errors = [record for record in records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    primary = logging.Formatter().format(errors[0])
    assert "in handler" in primary and "in __aexit__" not in primary
    formatted = "\n".join(logging.Formatter().format(record) for record in records)
    assert sensitive not in formatted and container.sensitive not in formatted


@pytest.mark.asyncio
async def test_external_cancellation_survives_cleanup_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cleanup diagnostics preserve external cancellation instead of failing a job."""
    started = asyncio.Event()
    container = _FailingLifecycleContainer(fail_enter=False)

    async def handler(_context: JobExecutionContext) -> None:
        started.set()
        await asyncio.Event().wait()

    caplog.set_level(logging.WARNING, logger="azents.job_runtime.local")
    runtime = _runtime(handler, container_factory=lambda: container)
    handle = await runtime.submit(_request("cancel-cleanup"))
    assert isinstance(handle, LocalJobHandle)
    await started.wait()
    handle.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handle.wait()

    records = [
        record for record in caplog.records if record.name == "azents.job_runtime.local"
    ]
    assert not any(record.levelno == logging.ERROR for record in records)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert container.sensitive not in logging.Formatter().format(records[0])
    assert runtime.active_count == 0
