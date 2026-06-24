"""SecurityService tests."""

import datetime
from unittest.mock import AsyncMock

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import (
    AuthConfig,
    EmailConfig,
    JWTConfig,
    RefreshTokenConfig,
    SignupTokenConfig,
)
from azents.core.email.service import EmailService
from azents.rdb.session import SessionManager
from azents.repos.email_verification import EmailVerificationRepository
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services.credential.providers import (
    EmailCredentialProvider,
    PasswordCredentialProvider,
)
from azents.services.credential.service import CredentialService
from azents.services.security import SecurityService
from azents.services.security.data import (
    GetAuthMethodsInput,
    LastCredentialRemovalDenied,
    RemovePasswordInput,
    SetPasswordInput,
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


def _make_email_service(*, configured: bool) -> EmailService:
    """Create EmailService for tests."""
    if not configured:
        service = EmailService(config=None, ses_client=None)
    else:
        service = EmailService(
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
    service.send_verification_code = AsyncMock()
    return service


def _make_service(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    email_configured: bool,
) -> SecurityService:
    """Create SecurityService for tests."""
    email_service = _make_email_service(configured=email_configured)
    return SecurityService(
        email_service=email_service,
        email_verification_repo=EmailVerificationRepository(),
        password_login_repo=PasswordLoginRepository(),
        user_repo=UserRepository(),
        credential_service=CredentialService(
            session_manager=rdb_session_manager,
            providers=[
                PasswordCredentialProvider(),
                EmailCredentialProvider(email_service=email_service),
            ],
            user_repo=UserRepository(),
        ),
        session_manager=rdb_session_manager,
        auth_config=_TEST_AUTH_CONFIG,
        email_config=email_service.config,
    )


class TestSecurityServiceCredentialMethods:
    """Credential-based security method tests."""

    async def test_get_auth_methods_marks_email_invalid_without_smtp(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Verified email is marked invalid when SMTP is disabled."""
        async with rdb_session_manager() as session:
            user = await UserRepository().create_with_verified_primary_email(
                session,
                UserCreate(email="security-email@example.com"),
                verified_at=datetime.datetime.now(datetime.UTC),
            )

        service = _make_service(rdb_session_manager, email_configured=False)

        result = await service.get_auth_methods(GetAuthMethodsInput(user_id=user.id))

        assert isinstance(result, Success)
        email = next(
            method for method in result.value.methods if method.type == "email"
        )
        assert email.configured
        assert not email.valid
        assert not email.enabled
        assert email.unavailable_reason == "smtp_not_configured"

    async def test_remove_password_rejects_last_valid_credential(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject deletion of password that is last valid credential."""
        service = _make_service(rdb_session_manager, email_configured=False)
        async with rdb_session_manager() as session:
            user = await UserRepository().create_with_verified_primary_email(
                session,
                UserCreate(email="remove-denied@example.com"),
                verified_at=datetime.datetime.now(datetime.UTC),
            )
        set_result = await service.set_password(
            SetPasswordInput(
                user_id=user.id,
                password="Aa123456!",
            )
        )
        assert isinstance(set_result, Success)

        result = await service.remove_password(RemovePasswordInput(user_id=user.id))

        assert isinstance(result, Failure)
        assert isinstance(result.error, LastCredentialRemovalDenied)

    async def test_remove_password_allows_when_email_is_valid(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Allow password deletion when verified email is valid credential."""
        service = _make_service(rdb_session_manager, email_configured=True)
        async with rdb_session_manager() as session:
            user = await UserRepository().create_with_verified_primary_email(
                session,
                UserCreate(email="remove-allowed@example.com"),
                verified_at=datetime.datetime.now(datetime.UTC),
            )
        set_result = await service.set_password(
            SetPasswordInput(
                user_id=user.id,
                password="Aa123456!",
            )
        )
        assert isinstance(set_result, Success)

        result = await service.remove_password(RemovePasswordInput(user_id=user.id))

        assert isinstance(result, Success)
        async with rdb_session_manager() as session:
            password_login = await PasswordLoginRepository().get_by_user_id(
                session,
                user.id,
            )
        assert password_login is None
