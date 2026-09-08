"""Security completed-operation database regressions."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.password_login import RDBPasswordLogin
from azents.rdb.models.user_email import RDBUserEmail
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.security_operation import (
    PasswordRemovalOutcome,
    SecurityOperationRepository,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate


def _repository(
    session_manager: SessionManager[AsyncSession],
) -> SecurityOperationRepository:
    return SecurityOperationRepository(
        user_repository=UserRepository(),
        password_repository=PasswordLoginRepository(),
        session_manager=session_manager,
    )


async def test_password_upsert_preserves_identity_and_replaces_hash(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Repeated setup changes the hash without creating a second credential."""
    repository = _repository(rdb_session_manager)
    async with rdb_session_manager() as session:
        user = await UserRepository().create_with_verified_primary_email(
            session,
            UserCreate(email="security-upsert@example.com"),
            verified_at=datetime.datetime.now(datetime.UTC),
        )
    assert await repository.set_password(user.id, "first-hash")
    first = await repository.get_password(user.id)
    assert first is not None
    assert await repository.set_password(user.id, "second-hash")
    second = await repository.get_password(user.id)
    assert second is not None
    assert second.id == first.id
    assert second.password_hash == "second-hash"
    async with rdb_session_manager() as session:
        count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBPasswordLogin)
            .where(RDBPasswordLogin.user_id == user.id)
        )
    assert count == 1
    assert not await repository.set_password("missing-user", "unused-hash")


async def test_removal_rechecks_email_after_earlier_eligible_snapshot(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A stale eligible read cannot delete the last valid credential."""
    repository = _repository(rdb_session_manager)
    async with rdb_session_manager() as session:
        user = await UserRepository().create_with_verified_primary_email(
            session,
            UserCreate(email="security-stale-email@example.com"),
            verified_at=datetime.datetime.now(datetime.UTC),
        )
    assert await repository.set_password(user.id, "stored-hash")
    async with rdb_session_manager() as session:
        assert await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBUserEmail.user_id == user.id,
                    RDBUserEmail.verified_at.is_not(None),
                )
            )
        )
        await session.execute(
            sa.update(RDBUserEmail)
            .where(RDBUserEmail.user_id == user.id)
            .values(verified_at=None)
        )
    assert (
        await repository.remove_password(
            user.id,
            email_available=True,
        )
        is PasswordRemovalOutcome.LAST_CREDENTIAL
    )
    assert await repository.get_password(user.id) is not None
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBUserEmail)
            .where(RDBUserEmail.user_id == user.id)
            .values(verified_at=datetime.datetime.now(datetime.UTC))
        )
    assert (
        await repository.remove_password(
            user.id,
            email_available=False,
        )
        is PasswordRemovalOutcome.LAST_CREDENTIAL
    )
    assert (
        await repository.remove_password(
            user.id,
            email_available=True,
        )
        is PasswordRemovalOutcome.REMOVED
    )
    assert (
        await repository.remove_password(
            user.id,
            email_available=True,
        )
        is PasswordRemovalOutcome.NOT_SET
    )
