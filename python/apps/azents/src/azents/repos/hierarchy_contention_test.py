"""Narrow failure and cancellation contracts for complete hierarchy DB recovery."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from psycopg import OperationalError as DriverOperationalError
from psycopg.errors import DeadlockDetected, LockNotAvailable, SerializationFailure
from sqlalchemy.exc import OperationalError

from azents.repos.hierarchy_contention import retry_hierarchy_operation


@pytest.mark.parametrize("abort", [DeadlockDetected, SerializationFailure])
async def test_confirmed_abort_retries_after_complete_scope_exit_with_original_inputs(
    abort: type[DriverOperationalError],
) -> None:
    boundaries: list[str] = []
    original_owner = object()
    original_output = object()
    attempts = 0

    @asynccontextmanager
    async def scope() -> AsyncIterator[None]:
        boundaries.append("open")
        try:
            yield
        except OperationalError:
            boundaries.append("rollback")
            raise
        else:
            boundaries.append("commit")
        finally:
            boundaries.append("close")

    @retry_hierarchy_operation
    async def operation(owner: object, output: object) -> str:
        nonlocal attempts
        assert owner is original_owner
        assert output is original_output
        attempts += 1
        async with scope():
            if attempts == 1:
                raise OperationalError("mutation", {}, abort("aborted"))
            return "committed"

    assert await operation(original_owner, original_output) == "committed"
    assert attempts == 2
    assert boundaries == ["open", "rollback", "close", "open", "commit", "close"]


@pytest.mark.parametrize(
    "failure",
    [
        OperationalError("mutation", {}, LockNotAvailable("inherited timeout")),
        OperationalError(
            "COMMIT",
            {},
            DriverOperationalError("connection lost"),
            connection_invalidated=True,
        ),
        PermissionError("stale owner"),
        ValueError("invalid target"),
        TimeoutError("operation deadline"),
    ],
)
async def test_non_abort_failure_and_unknown_commit_do_not_retry(
    failure: Exception,
) -> None:
    attempts = 0

    @retry_hierarchy_operation
    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise failure

    with pytest.raises(type(failure)) as observed:
        await operation()
    assert observed.value is failure
    assert attempts == 1


async def test_blocked_operation_cancellation_closes_scope_without_replay() -> None:
    entered = asyncio.Event()
    released = asyncio.Event()
    attempts = 0
    never_release = asyncio.Event()

    @retry_hierarchy_operation
    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        try:
            entered.set()
            await never_release.wait()
        finally:
            released.set()

    task = asyncio.create_task(operation())
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released.is_set()
    assert attempts == 1


async def test_cancellation_after_confirmed_abort_does_not_restart() -> None:
    attempts = 0

    @retry_hierarchy_operation
    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        task = asyncio.current_task()
        assert task is not None
        task.cancel()
        raise OperationalError("mutation", {}, DeadlockDetected("aborted"))

    task = asyncio.create_task(operation())
    with pytest.raises(asyncio.CancelledError):
        await task
    assert attempts == 1
