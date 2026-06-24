"""PasswordResetTokenService tests."""

import datetime

from azcommon.logging import RuntimeEnvironment
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_reset_token import PasswordResetTokenRepository
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.user_email import UserEmailRepository
from azents.services._utils import generate_refresh_token
from azents.services.password_reset_token import (
    PasswordResetTokenService,
    hash_password_reset_token,
)
from azents.services.password_reset_token.data import (
    CreatePasswordResetTokenInput,
    InvalidPasswordResetToken,
    PreviewPasswordResetTokenInput,
    RedeemPasswordResetTokenInput,
    WeakResetPassword,
)


def _make_service(
    rdb_session_manager: SessionManager[AsyncSession],
) -> PasswordResetTokenService:
    """Create PasswordResetTokenService for tests."""
    return PasswordResetTokenService(
        password_reset_token_repo=PasswordResetTokenRepository(),
        user_repo=UserRepository(),
        user_email_repo=UserEmailRepository(),
        password_login_repo=PasswordLoginRepository(),
        session_repo=SessionRepository(),
        session_manager=rdb_session_manager,
        config=Config.model_construct(
            runtime_env=RuntimeEnvironment.LOCAL,
            web_url="https://azents.example.com",
        ),
    )


class TestPasswordResetTokenService:
    """PasswordResetTokenService tests."""

    async def test_create_returns_plaintext_once_without_hash(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Create response returns plaintext token and list does not expose hash."""
        service = _make_service(rdb_session_manager)
        async with rdb_session_manager() as session:
            user = await UserRepository().create_with_verified_primary_email(
                session,
                UserCreate(email="reset-create@example.com"),
                verified_at=datetime.datetime.now(datetime.UTC),
            )

        result = await service.create(
            CreatePasswordResetTokenInput(
                user_id=user.id,
                email=None,
                created_by_user_id=None,
                expires_at=None,
            )
        )

        assert isinstance(result, Success)
        assert result.value.plaintext_token
        assert result.value.reset_url.startswith("https://azents.example.com")
        listed = await service.list_all()
        dumped = listed.items[0].model_dump()
        assert "plaintext_token" not in dumped
        assert "token_hash" not in dumped

    async def test_preview_masks_current_user_email(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Preview masks current user email hint."""
        service = _make_service(rdb_session_manager)
        async with rdb_session_manager() as session:
            user = await UserRepository().create_with_verified_primary_email(
                session,
                UserCreate(email="preview@example.com"),
                verified_at=datetime.datetime.now(datetime.UTC),
            )
        created = await service.create(
            CreatePasswordResetTokenInput(
                user_id=user.id,
                email=None,
                created_by_user_id=None,
                expires_at=None,
            )
        )
        assert isinstance(created, Success)

        preview = await service.preview(
            PreviewPasswordResetTokenInput(token=created.value.plaintext_token)
        )

        assert preview.valid
        assert preview.email == "p***@example.com"

    async def test_redeem_sets_password_revokes_sessions_and_audits(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """On redeem success, set password and revoke existing sessions."""
        service = _make_service(rdb_session_manager)
        refresh_token = generate_refresh_token()
        async with rdb_session_manager() as session:
            user = await UserRepository().create_with_verified_primary_email(
                session,
                UserCreate(email="redeem@example.com"),
                verified_at=datetime.datetime.now(datetime.UTC),
            )
            db_session = await SessionRepository().create(
                session,
                SessionCreate(
                    user_id=user.id,
                    refresh_token=refresh_token,
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(days=1),
                    max_expires_at=None,
                    user_agent="pytest",
                    ip_address="127.0.0.1",
                ),
            )
        created = await service.create(
            CreatePasswordResetTokenInput(
                user_id=user.id,
                email=None,
                created_by_user_id=None,
                expires_at=None,
            )
        )
        assert isinstance(created, Success)

        result = await service.redeem(
            RedeemPasswordResetTokenInput(
                token=created.value.plaintext_token,
                password="Aa123456!",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )

        assert isinstance(result, Success)
        async with rdb_session_manager() as session:
            password_login = await PasswordLoginRepository().get_by_user_id(
                session,
                user.id,
            )
            revoked_session = await SessionRepository().get(session, db_session.id)
            token = await PasswordResetTokenRepository().get_by_token_hash(
                session,
                hash_password_reset_token(created.value.plaintext_token),
            )
            assert token is not None
            redemptions = (
                await PasswordResetTokenRepository().list_redemptions_by_token_id(
                    session,
                    token.id,
                )
            )
        assert password_login is not None
        assert revoked_session is not None
        assert revoked_session.revoked_at is not None
        assert token.used_at is not None
        assert len(redemptions) == 1

    async def test_weak_password_does_not_consume_token(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Weak password failure does not consume reset token."""
        service = _make_service(rdb_session_manager)
        async with rdb_session_manager() as session:
            user = await UserRepository().create_with_verified_primary_email(
                session,
                UserCreate(email="weak-reset@example.com"),
                verified_at=datetime.datetime.now(datetime.UTC),
            )
        created = await service.create(
            CreatePasswordResetTokenInput(
                user_id=user.id,
                email=None,
                created_by_user_id=None,
                expires_at=None,
            )
        )
        assert isinstance(created, Success)

        result = await service.redeem(
            RedeemPasswordResetTokenInput(
                token=created.value.plaintext_token,
                password="short",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, WeakResetPassword)
        async with rdb_session_manager() as session:
            token = await PasswordResetTokenRepository().get_by_token_hash(
                session,
                hash_password_reset_token(created.value.plaintext_token),
            )
        assert token is not None
        assert token.used_at is None

    async def test_redeem_rejects_reused_token(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject reuse of single-use reset token."""
        service = _make_service(rdb_session_manager)
        async with rdb_session_manager() as session:
            user = await UserRepository().create_with_verified_primary_email(
                session,
                UserCreate(email="reuse-reset@example.com"),
                verified_at=datetime.datetime.now(datetime.UTC),
            )
        created = await service.create(
            CreatePasswordResetTokenInput(
                user_id=user.id,
                email=None,
                created_by_user_id=None,
                expires_at=None,
            )
        )
        assert isinstance(created, Success)
        first = await service.redeem(
            RedeemPasswordResetTokenInput(
                token=created.value.plaintext_token,
                password="Aa123456!",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )
        assert isinstance(first, Success)

        second = await service.redeem(
            RedeemPasswordResetTokenInput(
                token=created.value.plaintext_token,
                password="Aa123456!",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )

        assert isinstance(second, Failure)
        assert isinstance(second.error, InvalidPasswordResetToken)
