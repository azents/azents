"""Recover the finite hierarchy database-operation closure after confirmed aborts."""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any

from psycopg.errors import DeadlockDetected, SerializationFailure
from sqlalchemy.exc import OperationalError


def retry_hierarchy_operation[**P, R](
    operation: Callable[P, Awaitable[R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """Repeat an owning DB-only operation after its aborted scope has closed.

    Apply only to the enumerated hierarchy and terminal transaction owners. The
    operation owns its fresh session and accepting commit on every invocation;
    composing in-session helpers and external execution are outside this boundary.
    Original arguments retain their authority identity through every attempt.
    """

    @wraps(operation)
    async def retry(*args: P.args, **kwargs: P.kwargs) -> R:
        while True:
            try:
                return await operation(*args, **kwargs)
            except asyncio.CancelledError:
                raise
            except OperationalError as error:
                if not isinstance(error.orig, DeadlockDetected | SerializationFailure):
                    raise
                # PostgreSQL confirms this transaction aborted. The complete
                # owning operation has exited, releasing its partial row set.
                await asyncio.sleep(0)

    return retry
