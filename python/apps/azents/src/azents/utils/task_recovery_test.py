"""Hard-bounded asynchronous task recovery primitive tests."""

import asyncio

import pytest

import azents.utils.task_recovery as task_recovery_module
from azents.utils.task_recovery import (
    compensate_then_reraise,
    run_bounded_cancellation_safe,
)


async def test_caller_cancellation_is_immediate_while_recovery_finishes() -> None:
    """Caller cancellation wins immediately without abandoning bounded recovery."""
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def operation() -> None:
        started.set()
        await release.wait()
        completed.set()

    task = asyncio.create_task(
        run_bounded_cancellation_safe(operation, timeout_seconds=1.0)
    )
    await started.wait()
    task.cancel("caller cancelled")

    with pytest.raises(asyncio.CancelledError, match="caller cancelled"):
        await asyncio.wait_for(task, timeout=0.1)
    assert not completed.is_set()

    release.set()
    await asyncio.wait_for(completed.wait(), timeout=1)
    await _wait_for_retained_recovery_release()
    assert completed.is_set()


async def test_bounded_operation_times_out() -> None:
    """A stuck recovery operation cannot block shutdown indefinitely."""
    never = asyncio.Event()

    with pytest.raises(TimeoutError):
        await run_bounded_cancellation_safe(
            never.wait,
            timeout_seconds=0.01,
        )


async def test_timeout_quarantines_cancellation_swallowing_operation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A recovery coroutine cannot defeat the deadline by swallowing cancel."""
    started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()

    async def operation() -> None:
        started.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancellation_seen.set()
        raise RuntimeError("late recovery failure")

    operation_call = asyncio.create_task(
        run_bounded_cancellation_safe(operation, timeout_seconds=0.01)
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    with pytest.raises(TimeoutError, match="Recovery operation exceeded"):
        await asyncio.wait_for(operation_call, timeout=1)

    await asyncio.wait_for(cancellation_seen.wait(), timeout=1)
    retained_operation = next(
        task
        for task in task_recovery_module._RETAINED_RECOVERY_TASKS  # pyright: ignore[reportPrivateUsage]
        if task.get_name() == "recovery-operation" and not task.done()
    )

    loop = asyncio.get_running_loop()
    previous_exception_handler = loop.get_exception_handler()
    unobserved_contexts: list[dict[str, object]] = []
    loop.set_exception_handler(
        lambda _loop, context: unobserved_contexts.append(context)
    )
    try:
        release.set()
        await _wait_for_retained_recovery_release()
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous_exception_handler)

    assert retained_operation.done()
    assert "Detached recovery task failed" in caplog.text
    assert unobserved_contexts == []


async def test_fresh_cancellation_wins_over_late_recovery_failure() -> None:
    """A late background failure cannot replace the caller's cancellation reason."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def operation() -> None:
        started.set()
        await release.wait()
        raise RuntimeError("late recovery failure")

    task = asyncio.create_task(
        run_bounded_cancellation_safe(operation, timeout_seconds=1.0)
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel("fresh cancellation")
    release.set()

    with pytest.raises(asyncio.CancelledError) as cancelled:
        await asyncio.wait_for(task, timeout=0.1)

    assert cancelled.value.args == ("fresh cancellation",)
    await _wait_for_retained_recovery_release()


async def test_compensation_failure_preserves_primary_cancellation_reason() -> None:
    """A cleanup failure cannot replace the stop reason being propagated."""
    primary_error = asyncio.CancelledError("user stop")

    async def failed_compensation() -> None:
        raise asyncio.CancelledError("cleanup transport cancelled")

    with pytest.raises(asyncio.CancelledError) as raised:
        await compensate_then_reraise(
            failed_compensation,
            primary_error=primary_error,
        )

    assert raised.value is primary_error
    assert raised.value.args == ("user stop",)
    assert isinstance(raised.value.__cause__, asyncio.CancelledError)


async def test_fresh_compensation_cancellation_supersedes_non_cancel_error() -> None:
    """A newly requested stop cannot be swallowed by an older ordinary failure."""
    primary_error = RuntimeError("upload failed")
    compensation_started = asyncio.Event()

    async def blocked_compensation() -> None:
        compensation_started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        compensate_then_reraise(
            blocked_compensation,
            primary_error=primary_error,
        )
    )
    await asyncio.wait_for(compensation_started.wait(), timeout=1)
    task.cancel("user stop")

    with pytest.raises(asyncio.CancelledError) as raised:
        await task

    assert raised.value.args == ("user stop",)
    assert raised.value.__cause__ is primary_error


async def test_internal_compensation_cancellation_preserves_primary_error() -> None:
    """A child cancellation without caller cancel remains a recovery failure."""
    primary_error = RuntimeError("upload failed")

    async def internally_cancelled_compensation() -> None:
        raise asyncio.CancelledError("cleanup transport cancelled")

    with pytest.raises(RuntimeError, match="upload failed") as raised:
        await compensate_then_reraise(
            internally_cancelled_compensation,
            primary_error=primary_error,
        )

    assert raised.value is primary_error
    assert isinstance(raised.value.__cause__, asyncio.CancelledError)


async def test_fatal_compensation_signal_is_not_hidden_by_primary_error() -> None:
    """BaseException control signals propagate instead of being rewritten."""

    class FatalRecoverySignal(BaseException):
        """Represent a process-level control signal for the unit test."""

    fatal = FatalRecoverySignal("terminate")

    async def fatal_compensation() -> None:
        raise fatal

    with pytest.raises(FatalRecoverySignal) as raised:
        await compensate_then_reraise(
            fatal_compensation,
            primary_error=RuntimeError("upload failed"),
        )

    assert raised.value is fatal


async def _wait_for_retained_recovery_release() -> None:
    """Wait until every background recovery outcome has been observed."""

    async def wait_until_empty() -> None:
        while task_recovery_module._RETAINED_RECOVERY_TASKS:  # pyright: ignore[reportPrivateUsage]
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_until_empty(), timeout=1)
