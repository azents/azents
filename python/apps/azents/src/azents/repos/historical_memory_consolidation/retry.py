"""Retry only completed, rollback-confirmed private database operations."""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any, Concatenate, Protocol

from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityBusyError,
    ConsolidationDeadlineError,
    consolidation_session,
    observe_attempt_seconds,
)

_CONTENTION_YIELD_SECONDS = 0.05


async def wait_for_contention_retry() -> None:
    """Yield after rollback without adding a count, token or time cutoff."""
    await asyncio.sleep(_CONTENTION_YIELD_SECONDS)


class ConsolidationOperationRepository(Protocol):
    """The existing repository resource needed to observe the same claim's time."""

    @property
    def session_manager(self) -> SessionManager[WriteSession]: ...


def retry_rolled_back_operation[**P, R](
    operation: Callable[P, Awaitable[R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """Retry confirmed aborts under the caller's existing lifetime/cancellation."""

    @wraps(operation)
    async def retry(*args: P.args, **kwargs: P.kwargs) -> R:
        while True:
            try:
                return await operation(*args, **kwargs)
            except ConsolidationAuthorityBusyError:
                # The owning repository has closed its transaction and rolled back.
                await wait_for_contention_retry()

    return retry


def retry_consolidation_operation[Repository: ConsolidationOperationRepository, **P, R](
    operation: Callable[
        Concatenate[Repository, ConsolidationJobPrincipal, P], Awaitable[R]
    ],
) -> Callable[
    Concatenate[Repository, ConsolidationJobPrincipal, P], Coroutine[Any, Any, R]
]:
    """Repeat a DB-only method after rollback, never its caller's external work.

    The captured absolute attempt cutoff is conservative, not live authority.
    Every try acquires and validates fresh fenced ownership in its own transaction.
    Deadline and cancellation are not retryable; neither is ambiguous commit.
    """
    retry_operation = retry_rolled_back_operation(operation)

    @wraps(operation)
    async def retry(
        repository: Repository,
        principal: ConsolidationJobPrincipal,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        async with consolidation_session(repository.session_manager) as session:
            remaining = await observe_attempt_seconds(session, principal)
            deadline = asyncio.get_running_loop().time() + remaining
        timeout = asyncio.timeout_at(deadline)
        try:
            async with timeout:
                return await retry_operation(repository, principal, *args, **kwargs)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            if not timeout.expired():
                raise
            raise ConsolidationDeadlineError(
                "Consolidation database deadline was exceeded."
            ) from None

    return retry
