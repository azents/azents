"""SignupTokenService tests."""

import datetime
from unittest.mock import AsyncMock

from azcommon.logging import RuntimeEnvironment
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import (
    AuthConfig,
    Config,
    EmailConfig,
    JWTConfig,
    RefreshTokenConfig,
    SignupTokenConfig,
)
from azents.core.email.service import EmailService
from azents.core.enums import SignupTokenDeliveryMethod
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.session import SessionRepository
from azents.repos.signup_token import SignupTokenRepository
from azents.repos.user import UserRepository
from azents.repos.user_email import UserEmailRepository
from azents.services.signup_token import SignupTokenService, hash_signup_token
from azents.services.signup_token.data import (
    CreateSignupTokenInput,
    InvalidSignupToken,
    RedeemSignupTokenInput,
    SignupEmailDeliveryUnavailable,
    SignupTokenEmailMismatch,
    WeakSignupPassword,
)

_TEST_AUTH_CONFIG = AuthConfig(
    jwt=JWTConfig(
        secret_key="test-secret-key-for-jwt-signing-1234567890",
        algorithm="HS256",
        access_token_expire_minutes=30,
    ),
    refresh_token=RefreshTokenConfig(
        expire_days=180,
        rotation_period_minutes=10,
        grace_period_minutes=5,
    ),
    signup_token=SignupTokenConfig(default_expire_hours=168, default_max_uses=1),
)


def _make_service(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    email_service: EmailService | None = None,
) -> SignupTokenService:
    """Create SignupTokenService for tests."""
    if email_service is None:
        email_service = EmailService(config=None, ses_client=None)
    return SignupTokenService(
        signup_token_repo=SignupTokenRepository(),
        user_repo=UserRepository(),
        user_email_repo=UserEmailRepository(),
        password_login_repo=PasswordLoginRepository(),
        session_repo=SessionRepository(),
        email_service=email_service,
        session_manager=rdb_session_manager,
        auth_config=_TEST_AUTH_CONFIG,
        config=Config.model_construct(
            runtime_env=RuntimeEnvironment.LOCAL,
            web_url="https://azents.example.com",
        ),
    )


class TestSignupTokenService:
    """SignupTokenService tests."""

    async def test_list_all_excludes_plaintext_token_and_hash(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """List output does not include plaintext token or token hash."""
        service = _make_service(rdb_session_manager)
        await service.create(
            CreateSignupTokenInput(
                email="listed@example.com",
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=None,
                max_uses=None,
            )
        )

        result = await service.list_all()

        assert result.total == 1
        dumped = result.items[0].model_dump()
        assert "plaintext_token" not in dumped
        assert "token_hash" not in dumped

    async def test_redeem_creates_verified_user_and_session(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """On redeem success, create verified UserEmail and session."""
        service = _make_service(rdb_session_manager)
        created = await service.create(
            CreateSignupTokenInput(
                email="NewUser@example.com",
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=None,
                max_uses=None,
            )
        )

        result = await service.redeem(
            RedeemSignupTokenInput(
                token=created.plaintext_token,
                email="newuser@example.com",
                password="Aa123456!",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )

        assert isinstance(result, Success)
        assert result.value.access_token
        async with rdb_session_manager() as session:
            user_email = await UserEmailRepository().get_by_email(
                session,
                "newuser@example.com",
            )
            assert user_email is not None
            password_login = await PasswordLoginRepository().get_by_user_id(
                session,
                user_email.user_id,
            )
            session_record = await SessionRepository().get_by_refresh_token(
                session,
                result.value.refresh_token,
            )
            token = await SignupTokenRepository().get_by_token_hash(
                session,
                hash_signup_token(created.plaintext_token),
            )
            assert token is not None
            redemptions = await SignupTokenRepository().list_redemptions_by_token_id(
                session,
                token.id,
            )
        assert user_email.verified_at is not None
        assert password_login is not None
        assert session_record is not None
        assert len(redemptions) == 1
        assert redemptions[0].user_id == user_email.user_id

    async def test_redeem_rejects_email_mismatch(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject redeem when token email differs from input email."""
        service = _make_service(rdb_session_manager)
        created = await service.create(
            CreateSignupTokenInput(
                email="target@example.com",
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=None,
                max_uses=None,
            )
        )

        result = await service.redeem(
            RedeemSignupTokenInput(
                token=created.plaintext_token,
                email="other@example.com",
                password="Aa123456!",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, SignupTokenEmailMismatch)
        async with rdb_session_manager() as session:
            token = await SignupTokenRepository().get_by_token_hash(
                session,
                hash_signup_token(created.plaintext_token),
            )
        assert token is not None
        assert token.used_count == 0

    async def test_redeem_rejects_weak_password_without_consuming_token(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Weak password failure does not increase token use count."""
        service = _make_service(rdb_session_manager)
        created = await service.create(
            CreateSignupTokenInput(
                email="weak@example.com",
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=None,
                max_uses=None,
            )
        )

        result = await service.redeem(
            RedeemSignupTokenInput(
                token=created.plaintext_token,
                email="weak@example.com",
                password="short",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, WeakSignupPassword)
        async with rdb_session_manager() as session:
            token = await SignupTokenRepository().get_by_token_hash(
                session,
                hash_signup_token(created.plaintext_token),
            )
        assert token is not None
        assert token.used_count == 0

    async def test_redeem_rejects_existing_email_without_consuming_token(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Already-signed-up email failure does not increase token use count."""
        service = _make_service(rdb_session_manager)
        existing = await service.create(
            CreateSignupTokenInput(
                email="existing@example.com",
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=None,
                max_uses=None,
            )
        )
        first = await service.redeem(
            RedeemSignupTokenInput(
                token=existing.plaintext_token,
                email="existing@example.com",
                password="Aa123456!",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )
        assert isinstance(first, Success)

        created = await service.create(
            CreateSignupTokenInput(
                email="existing@example.com",
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=None,
                max_uses=None,
            )
        )

        result = await service.redeem(
            RedeemSignupTokenInput(
                token=created.plaintext_token,
                email="existing@example.com",
                password="Aa123456!",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )

        assert isinstance(result, Failure)
        async with rdb_session_manager() as session:
            token = await SignupTokenRepository().get_by_token_hash(
                session,
                hash_signup_token(created.plaintext_token),
            )
        assert token is not None
        assert token.used_count == 0

    async def test_redeem_rejects_reused_single_use_token(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject reuse of single-use token."""
        service = _make_service(rdb_session_manager)
        created = await service.create(
            CreateSignupTokenInput(
                email="single@example.com",
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=None,
                max_uses=None,
            )
        )
        first = await service.redeem(
            RedeemSignupTokenInput(
                token=created.plaintext_token,
                email="single@example.com",
                password="Aa123456!",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )
        assert isinstance(first, Success)

        second = await service.redeem(
            RedeemSignupTokenInput(
                token=created.plaintext_token,
                email="single@example.com",
                password="Aa123456!",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )

        assert isinstance(second, Failure)
        assert isinstance(second.error, InvalidSignupToken)

    async def test_redeem_rejects_expired_token(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject expired token redeem."""
        service = _make_service(rdb_session_manager)
        created = await service.create(
            CreateSignupTokenInput(
                email="expired@example.com",
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(minutes=1),
                max_uses=None,
            )
        )

        result = await service.redeem(
            RedeemSignupTokenInput(
                token=created.plaintext_token,
                email="expired@example.com",
                password="Aa123456!",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidSignupToken)

    async def test_redeem_rejects_revoked_token(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject revoked token redeem."""
        service = _make_service(rdb_session_manager)
        created = await service.create(
            CreateSignupTokenInput(
                email="revoked@example.com",
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=None,
                max_uses=None,
            )
        )
        revoked = await service.revoke(created.token.id)
        assert revoked

        result = await service.redeem(
            RedeemSignupTokenInput(
                token=created.plaintext_token,
                email="revoked@example.com",
                password="Aa123456!",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidSignupToken)

    async def test_create_email_delivery_token_sends_email(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Create token for email delivery and call mail send."""
        email_service = EmailService(
            config=EmailConfig(
                sender="noreply@example.com",
                sender_name="Azents",
                ses_region="us-west-2",
                ses_endpoint=None,
                verification_expire_minutes=10,
                web_url="https://azents.example.com",
            ),
            ses_client=object(),  # type: ignore[arg-type]
        )
        email_service.send_signup_token = AsyncMock(return_value=True)
        service = _make_service(rdb_session_manager, email_service=email_service)

        result = await service.create_email_delivery_token("mail@example.com")

        assert isinstance(result, Success)
        email_service.send_signup_token.assert_awaited_once()
        await_args = email_service.send_signup_token.await_args
        assert await_args is not None
        kwargs = await_args.kwargs
        assert kwargs["to_email"] == "mail@example.com"
        assert kwargs["signup_url"].startswith("https://azents.example.com/signup")

    async def test_create_email_delivery_token_requires_email_service(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Return delivery unavailable when email service is not configured."""
        service = _make_service(rdb_session_manager)

        result = await service.create_email_delivery_token("mail@example.com")

        assert isinstance(result, Failure)
        assert isinstance(result.error, SignupEmailDeliveryUnavailable)
