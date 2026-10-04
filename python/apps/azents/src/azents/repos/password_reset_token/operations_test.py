"""Actual password-reset atomicity and independent-read contracts."""

import asyncio
import dataclasses
import datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.rdb.models.password_login import RDBPasswordLogin
from azents.rdb.models.password_reset_token import RDBPasswordResetTokenRedemption
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import PasswordLoginCreate
from azents.repos.password_reset_token import PasswordResetTokenRepository
from azents.repos.password_reset_token.data import (
    PasswordResetTokenRedemption,
    PasswordResetTokenRedemptionCreate,
)
from azents.repos.password_reset_token.operations import (
    PasswordResetOperationRepository,
    ResetRedemption,
)
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate


class _FaultTokenRepository(PasswordResetTokenRepository):
    def __init__(self, *, cancel: bool) -> None:
        self.cancel = cancel

    async def create_redemption(
        self, session: WriteSession, create: PasswordResetTokenRedemptionCreate
    ) -> PasswordResetTokenRedemption:
        await super().create_redemption(session, create)
        if self.cancel:
            raise asyncio.CancelledError("isolated reset audit cancellation")
        raise RuntimeError("isolated reset audit failure")


def _operations(
    manager: SessionManager[WriteSession],
) -> PasswordResetOperationRepository:
    return PasswordResetOperationRepository(
        session_manager=manager,
        read_session_manager=manager,
        token_repository=PasswordResetTokenRepository(),
        user_repository=UserRepository(),
        password_repository=PasswordLoginRepository(),
        session_repository=SessionRepository(),
    )


@pytest.mark.parametrize("existing_password", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
async def test_failure_after_actual_redemption_rolls_back_whole_group(
    rdb_session_manager: SessionManager[WriteSession],
    existing_password: bool,
    cancel: bool,
) -> None:
    operations = _operations(rdb_session_manager)
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        user = await UserRepository().create_with_verified_primary_email(
            session,
            UserCreate(email=f"reset-fault-{uuid4().hex}@example.com"),
            verified_at=now,
        )
        auth = await SessionRepository().create(
            session,
            SessionCreate(
                user_id=user.id,
                refresh_token=uuid4().hex,
                expires_at=now + datetime.timedelta(days=1),
                max_expires_at=None,
                user_agent=None,
                ip_address=None,
            ),
        )
        if existing_password:
            await PasswordLoginRepository().create(
                session, PasswordLoginCreate(user_id=user.id, password_hash="old-hash")
            )
    token = await operations.create(
        user_id=user.id,
        email=None,
        token_hash=uuid4().hex,
        created_by_user_id=None,
        expires_at=now + datetime.timedelta(days=1),
    )
    assert token is not None
    failing = dataclasses.replace(
        operations, token_repository=_FaultTokenRepository(cancel=cancel)
    )
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await failing.redeem(
            command=ResetRedemption(
                token_hash=token.token_hash,
                password_hash="new-hash",
                now=now,
                ip_address=None,
                user_agent=None,
            )
        )
    async with rdb_session_manager() as session:
        observed = await PasswordResetTokenRepository().get_by_token_hash(
            session, token.token_hash
        )
        password = await PasswordLoginRepository().get_by_user_id(session, user.id)
        auth_observed = await SessionRepository().get(session, auth.id)
        records = await PasswordResetTokenRepository().list_redemptions_by_token_id(
            session, token.id
        )
    assert observed is not None and observed.used_at is None
    assert auth_observed is not None and auth_observed.revoked_at is None
    assert records == []
    if existing_password:
        assert password is not None and password.password_hash == "old-hash"
    else:
        assert password is None


async def test_native_read_only_preview_and_list_complete_without_writes(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    operations = dataclasses.replace(
        _operations(manager),
        read_session_manager=create_read_only_session_manager(rdb_engine),
    )
    now = datetime.datetime.now(datetime.UTC)
    async with manager() as session:
        user = await UserRepository().create_with_verified_primary_email(
            session,
            UserCreate(email=f"reset-read-{uuid4().hex}@example.com"),
            verified_at=now,
        )
    try:
        token = await operations.create(
            user_id=user.id,
            email=None,
            token_hash=uuid4().hex,
            created_by_user_id=None,
            expires_at=now + datetime.timedelta(days=1),
        )
        assert token is not None
        preview = await operations.preview(token_hash=token.token_hash, now=now)
        assert preview is not None and preview.email == user.primary_email
        assert token.id in {
            item.id for item in (await operations.list_all(offset=0, limit=50)).items
        }
        async with manager() as session:
            observed = await PasswordResetTokenRepository().get_by_token_hash(
                session, token.token_hash
            )
            assert observed is not None and observed.used_at is None
    finally:
        async with manager() as session:
            await session.write_session.execute(
                sa.delete(RDBPasswordResetTokenRedemption).where(
                    RDBPasswordResetTokenRedemption.user_id == user.id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBPasswordLogin).where(RDBPasswordLogin.user_id == user.id)
            )
            await UserRepository().delete(session, user.id)
