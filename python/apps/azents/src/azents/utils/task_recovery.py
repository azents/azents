"""Hard-bounded asynchronous task recovery primitives."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, NoReturn, TypeVar

_T = TypeVar("_T")

logger = logging.getLogger(__name__)

OPERATION_RECOVERY_TIMEOUT_SECONDS = 10.0
_RETAINED_RECOVERY_TASKS: set[asyncio.Task[Any]] = set()


def current_task_is_cancelling() -> bool:
    """Return whether cancellation was requested on the current caller task."""
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


def _on_retained_recovery_task_done(task: asyncio.Task[Any]) -> None:
    """Release and observe a detached recovery task."""
    _RETAINED_RECOVERY_TASKS.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("Detached recovery task failed", exc_info=True)


def _retain_recovery_task(task: asyncio.Task[Any]) -> None:
    """Strongly retain recovery work until its outcome has been consumed."""
    if task in _RETAINED_RECOVERY_TASKS:
        return
    _RETAINED_RECOVERY_TASKS.add(task)
    task.add_done_callback(_on_retained_recovery_task_done)


async def compensate_then_reraise(
    compensation: Callable[[], Awaitable[None]],
    *,
    primary_error: BaseException,
) -> NoReturn:
    """Preserve the primary failure unless a fresh cancellation supersedes it."""
    try:
        await compensation()
    except asyncio.CancelledError as compensation_cancellation:
        if (
            isinstance(primary_error, asyncio.CancelledError)
            or not current_task_is_cancelling()
        ):
            raise primary_error from compensation_cancellation
        raise compensation_cancellation from primary_error
    except Exception as compensation_error:
        raise primary_error from compensation_error
    raise primary_error


async def _run_with_hard_deadline(
    operation: Callable[[], Awaitable[_T]],
    *,
    timeout_seconds: float,
) -> _T:
    """Run one recovery operation without trusting cooperative cancellation."""

    async def invoke_operation() -> _T:
        return await operation()

    operation_task = asyncio.create_task(
        invoke_operation(),
        name="recovery-operation",
    )
    try:
        done, _ = await asyncio.wait(
            {operation_task},
            timeout=max(0.0, timeout_seconds),
        )
    except asyncio.CancelledError:
        operation_task.cancel()
        _retain_recovery_task(operation_task)
        raise

    if operation_task in done:
        return operation_task.result()

    operation_task.cancel()
    _retain_recovery_task(operation_task)
    raise TimeoutError(
        f"Recovery operation exceeded {timeout_seconds:.3f} second deadline"
    )


async def run_bounded_cancellation_safe(
    operation: Callable[[], Awaitable[_T]],
    *,
    timeout_seconds: float = OPERATION_RECOVERY_TIMEOUT_SECONDS,
) -> _T:
    """Run hard-bounded recovery while caller cancellation remains immediate."""
    bounded_task = asyncio.create_task(
        _run_with_hard_deadline(
            operation,
            timeout_seconds=timeout_seconds,
        ),
        name="bounded-recovery",
    )
    try:
        return await asyncio.shield(bounded_task)
    except asyncio.CancelledError:
        if not current_task_is_cancelling() and bounded_task.done():
            # ``asyncio.shield`` surfaces a child task's CancelledError as a
            # new, argument-less cancellation. Recover the original exception
            # so an operation-initiated cancellation keeps its reason. A real
            # caller cancellation remains authoritative even if completion
            # races with this branch.
            return bounded_task.result()
        # Caller cancellation stays authoritative and immediate. The retained
        # supervisor will either finish recovery or quarantine its operation at
        # the hard deadline without leaking an unobserved task outcome.
        _retain_recovery_task(bounded_task)
        raise
