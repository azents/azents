"""Expected context failure translation after complete repository DB scopes."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import pytest
from psycopg.errors import (
    DeadlockDetected,
    LockNotAvailable,
    QueryCanceled,
    SerializationFailure,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.historical_memory_context import MemoryContextAuthorityUnavailable
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.memory_context_snapshot import _authority_session


@pytest.mark.parametrize(
    "failure", [DeadlockDetected, LockNotAvailable, QueryCanceled, SerializationFailure]
)
@pytest.mark.parametrize("phase", ["enter", "body", "exit"])
async def test_only_expected_storage_orig_is_translated_after_scope_closes(
    failure: type[DeadlockDetected]
    | type[LockNotAvailable]
    | type[QueryCanceled]
    | type[SerializationFailure],
    phase: Literal["enter", "body", "exit"],
) -> None:
    original = OperationalError("read", {}, failure("Expected authority failure"))
    closed: list[bool] = []

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        try:
            if phase == "enter":
                raise original
            async with AsyncSession() as raw:
                yield ReadWriteSession(raw)
            if phase == "exit":
                raise original
        finally:
            closed.append(True)

    with pytest.raises(MemoryContextAuthorityUnavailable) as caught:
        async with _authority_session(manager):
            if phase == "body":
                raise original
    assert closed == [True]
    assert caught.value.__cause__ is original


@pytest.mark.parametrize(
    "failure",
    [OperationalError("read", {}, ValueError("unknown")), RuntimeError("unknown")],
)
async def test_unknown_storage_or_application_error_propagates_unchanged(
    failure: Exception,
) -> None:
    closed: list[bool] = []

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        try:
            async with AsyncSession() as raw:
                yield ReadWriteSession(raw)
        finally:
            closed.append(True)

    with pytest.raises(type(failure)) as caught:
        async with _authority_session(manager):
            raise failure
    assert caught.value is failure
    assert closed == [True]


async def test_context_cancellation_closes_scope_and_propagates() -> None:
    closed: list[bool] = []

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        try:
            async with AsyncSession() as raw:
                yield ReadWriteSession(raw)
        finally:
            closed.append(True)

    cancellation = asyncio.CancelledError("shutdown")
    with pytest.raises(asyncio.CancelledError) as caught:
        async with _authority_session(manager):
            raise cancellation
    assert caught.value is cancellation
    assert closed == [True]
