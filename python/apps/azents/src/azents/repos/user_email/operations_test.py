"""Completed UserEmail reads, conflict rollback and foreign-key preservation."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.user_email import DuplicateEmail, UserEmailCreate
from azents.rdb.models.user import RDBUser
from azents.rdb.models.user_email import RDBUserEmail
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.user import UserRepository
from azents.repos.user.data import User, UserCreate
from azents.repos.user_email import UserEmailRepository
from azents.repos.user_email.operations import UserEmailOperationRepository


class CommittedOperationManager:
    """Use independent PostgreSQL sessions with real commit and rollback."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        """Include commit-time deferred constraint failures in rollback."""
        async with AsyncSession(self.engine, expire_on_commit=False) as _raw_session:
            session = ReadWriteSession(_raw_session)
            try:
                yield session
                await session.write_session.commit()
            except BaseException:
                await session.write_session.rollback()
                raise


class ObservedEmailManager:
    """Observe actual transaction resolution before operation results return."""

    def __init__(self, manager: SessionManager[WriteSession]) -> None:
        self.manager = manager
        self.active = False
        self.resolved: list[bool] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        """Finish the underlying real lifetime on success or rollback."""
        self.active = True
        current: WriteSession | None = None
        try:
            async with self.manager() as session:
                current = session
                yield session
        finally:
            self.active = False
            if current is not None:
                self.resolved.append(not current.write_session.in_transaction())


async def _user(manager: SessionManager[WriteSession], name: str) -> User:
    """Create a User with its real primary email and deferred reference."""
    async with manager() as session:
        return await UserRepository().create(
            session, UserCreate(email=f"{name}@example.com")
        )


async def test_create_conflict_and_missing_delete_finish_with_unchanged_results(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Duplicate email rollback leaves one row and no lingering failed session."""
    user = await _user(rdb_session_manager, "email-operation-create")
    manager = ObservedEmailManager(rdb_session_manager)
    repository = UserEmailOperationRepository(manager, UserEmailRepository())
    request = UserEmailCreate(
        user_id=user.id, email="email-operation-additional@example.com"
    )
    created = await repository.create(request)
    assert isinstance(created, Success)
    assert created.value.verified_at is None
    duplicate = await repository.create(request)
    assert duplicate == Failure(DuplicateEmail(email=request.email))
    assert await repository.get(created.value.id) == created.value
    await repository.delete("0" * 32)
    await repository.delete(created.value.id)
    assert await repository.get(created.value.id) is None
    assert await repository.get(user.primary_email_id) is not None
    assert not manager.active
    assert manager.resolved == [True] * 7


async def test_user_order_and_global_page_count_are_preserved(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """User ascending order and global descending pagination retain exact totals."""
    user = await _user(rdb_session_manager, "email-operation-order")
    manager = ObservedEmailManager(rdb_session_manager)
    repository = UserEmailOperationRepository(manager, UserEmailRepository())
    ids = [user.primary_email_id]
    for name in ["first", "second", "third"]:
        result = await repository.create(
            UserEmailCreate(
                user_id=user.id, email=f"email-operation-{name}@example.com"
            )
        )
        assert isinstance(result, Success)
        ids.append(result.value.id)
    async with rdb_session_manager() as session:
        for index, id in enumerate(ids):
            await session.write_session.execute(
                sa.update(RDBUserEmail)
                .where(RDBUserEmail.id == id)
                .values(
                    created_at=datetime(2026, 1, 1, tzinfo=UTC)
                    + timedelta(seconds=index)
                )
            )
    by_user = await repository.list_by_user(user.id)
    assert by_user.total == 4
    assert [email.id for email in by_user.items] == ids
    page = await repository.list_all(offset=1, limit=1)
    assert page.total == 4
    assert [email.id for email in page.items] == [ids[2]]
    empty = await repository.list_by_user("0" * 32)
    assert empty.items == [] and empty.total == 0
    assert manager.resolved == [True] * 6
    assert not manager.active


async def test_nonunique_foreign_key_failure_propagates_after_rollback(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """An absent owner remains a foreign-key exception, not DuplicateEmail."""
    del latest_db_schema
    manager = ObservedEmailManager(CommittedOperationManager(rdb_engine))
    repository = UserEmailOperationRepository(manager, UserEmailRepository())
    with pytest.raises(IntegrityError):
        await repository.create(
            UserEmailCreate(
                user_id="0" * 32, email="email-operation-no-owner@example.com"
            )
        )
    assert not manager.active
    assert manager.resolved == [True]
    assert (await repository.list_all(offset=0, limit=50)).total == 0


async def test_primary_email_delete_retains_real_commit_time_foreign_key_failure(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Deleting a referenced primary email fails at real commit and restores it."""
    del latest_db_schema

    @asynccontextmanager
    async def committed_manager() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as _raw_session:
            session = ReadWriteSession(_raw_session)
            try:
                yield session
                await session.write_session.commit()
            except BaseException:
                await session.write_session.rollback()
                raise

    manager = ObservedEmailManager(committed_manager)
    user = await _user(committed_manager, f"email-operation-primary-{uuid4().hex}")
    repository = UserEmailOperationRepository(manager, UserEmailRepository())
    try:
        with pytest.raises(IntegrityError):
            await repository.delete(user.primary_email_id)
        assert not manager.active
        assert manager.resolved == [True]
        email = await repository.get(user.primary_email_id)
        assert email is not None and email.user_id == user.id
        async with committed_manager() as session:
            stored = await UserRepository().get(session, user.id)
            assert (
                stored is not None and stored.primary_email_id == user.primary_email_id
            )
    finally:
        async with committed_manager() as session:
            await session.write_session.execute(
                sa.delete(RDBUser).where(RDBUser.id == user.id)
            )
