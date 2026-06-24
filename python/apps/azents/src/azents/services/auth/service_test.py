"""AuthService tests."""

from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.auth.jwt import decode_access_token
from azents.core.config import (
    AuthConfig,
    JWTConfig,
    RefreshTokenConfig,
    SignupTokenConfig,
)
from azents.core.email.service import EmailService
from azents.rdb.session import SessionManager
from azents.repos.email_verification import EmailVerificationRepository
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.session import SessionRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.user_email import UserEmailRepository
from azents.services.credential.providers import (
    EmailCredentialProvider,
    PasswordCredentialProvider,
)
from azents.services.credential.service import CredentialService

from . import AuthService
from .data import (
    InvalidRefreshToken,
    InvalidVerificationCode,
    LogoutInput,
    RefreshTokenInput,
    RegistrationRequired,
    SendCodeInput,
    SessionNotFound,
    VerifyCodeInput,
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


def _make_email_service() -> EmailService:
    """EmailService for tests (works without SES)."""
    service = EmailService(config=None, ses_client=None)
    service.send_verification_code = AsyncMock()
    return service


def _make_auth_service(
    session_manager: SessionManager[AsyncSession],
) -> AuthService:
    """Create AuthService for tests."""
    email_service = _make_email_service()
    return AuthService(
        email_service=email_service,
        email_verification_repo=EmailVerificationRepository(),
        password_login_repo=PasswordLoginRepository(),
        user_repo=UserRepository(),
        user_email_repo=UserEmailRepository(),
        session_repo=SessionRepository(),
        credential_service=CredentialService(
            session_manager=session_manager,
            providers=[
                PasswordCredentialProvider(),
                EmailCredentialProvider(email_service=email_service),
            ],
            user_repo=UserRepository(),
        ),
        session_manager=session_manager,
        auth_config=_TEST_AUTH_CONFIG,
        email_config=None,
    )


class TestAuthServiceSendCode:
    """send_code tests."""

    async def test_send_code(
        self, rdb_session_manager: SessionManager[AsyncSession]
    ) -> None:
        """Send verification code."""
        # Given: prepare AuthService
        service = _make_auth_service(rdb_session_manager)

        # When: send verification code
        output = await service.send_code(SendCodeInput(email="send-code@example.com"))

        # Then: return CSRF token
        assert output.csrf_token
        assert len(output.csrf_token) == 64  # hex(32) = 64 characters


class TestAuthServiceVerifyCode:
    """verify_code tests."""

    async def test_verify_code_new_user_requires_signup_token(
        self, rdb_session_manager: SessionManager[AsyncSession]
    ) -> None:
        """New email verification does not create User without signup token."""
        service = _make_auth_service(rdb_session_manager)
        email = "verify-new@example.com"
        send_output = await service.send_code(SendCodeInput(email=email))

        async with rdb_session_manager() as session:
            verification = await service.email_verification_repo.get_by_email_and_csrf(
                session, email, send_output.csrf_token
            )
        assert verification is not None

        result = await service.verify_code(
            VerifyCodeInput(
                email=email,
                code=verification.code,
                csrf_token=send_output.csrf_token,
            )
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, RegistrationRequired)
        async with rdb_session_manager() as session:
            user_email = await UserEmailRepository().get_by_email(session, email)
        assert user_email is None

    async def test_verify_code_existing_user(
        self, rdb_session_manager: SessionManager[AsyncSession]
    ) -> None:
        """Verification with existing User email creates session for existing User."""
        service = _make_auth_service(rdb_session_manager)
        email = "verify-existing@example.com"
        async with rdb_session_manager() as session:
            await UserRepository().create(session, UserCreate(email=email))

        send2 = await service.send_code(SendCodeInput(email=email))
        async with rdb_session_manager() as session:
            v2 = await service.email_verification_repo.get_by_email_and_csrf(
                session, email, send2.csrf_token
            )
        assert v2 is not None
        result2 = await service.verify_code(
            VerifyCodeInput(email=email, code=v2.code, csrf_token=send2.csrf_token)
        )

        # Then: success
        assert isinstance(result2, Success)
        assert result2.value.access_token
        assert result2.value.refresh_token

    async def test_verify_code_wrong_code(
        self, rdb_session_manager: SessionManager[AsyncSession]
    ) -> None:
        """Verification fails with invalid verification code."""
        # Given: send verification code
        service = _make_auth_service(rdb_session_manager)
        email = "verify-wrong@example.com"
        send_output = await service.send_code(SendCodeInput(email=email))

        # When: verify with invalid code
        result = await service.verify_code(
            VerifyCodeInput(
                email=email,
                code="WRONG1",
                csrf_token=send_output.csrf_token,
            )
        )

        # Then: InvalidVerificationCode
        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidVerificationCode)

    async def test_verify_code_wrong_csrf(
        self, rdb_session_manager: SessionManager[AsyncSession]
    ) -> None:
        """Verification fails with invalid CSRF token."""
        # Given: send verification code
        service = _make_auth_service(rdb_session_manager)
        email = "verify-csrf@example.com"
        await service.send_code(SendCodeInput(email=email))

        # When: verify with invalid CSRF
        result = await service.verify_code(
            VerifyCodeInput(
                email=email,
                code="ABC123",
                csrf_token="wrong-csrf-token",
            )
        )

        # Then: InvalidVerificationCode
        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidVerificationCode)


class TestAuthServiceRefreshToken:
    """refresh_token tests."""

    async def _create_session(
        self, service: AuthService, session_manager: SessionManager[AsyncSession]
    ) -> tuple[str, str]:
        """Create session for tests and return (access_token, refresh_token)."""
        email = f"refresh-{id(self)}@example.com"
        async with session_manager() as session:
            await UserRepository().create(session, UserCreate(email=email))
        send_output = await service.send_code(SendCodeInput(email=email))
        async with session_manager() as session:
            verification = await service.email_verification_repo.get_by_email_and_csrf(
                session, email, send_output.csrf_token
            )
        assert verification is not None
        result = await service.verify_code(
            VerifyCodeInput(
                email=email,
                code=verification.code,
                csrf_token=send_output.csrf_token,
            )
        )
        assert isinstance(result, Success)
        return result.value.access_token, result.value.refresh_token

    async def test_refresh_token(
        self, rdb_session_manager: SessionManager[AsyncSession]
    ) -> None:
        """Refresh with valid refresh token."""
        # Given: create session
        service = _make_auth_service(rdb_session_manager)
        _, refresh_token = await self._create_session(service, rdb_session_manager)

        # When: refresh token
        result = await service.refresh_token(
            RefreshTokenInput(refresh_token=refresh_token)
        )

        # Then: success (return existing token because below rotation interval)
        assert isinstance(result, Success)
        assert result.value.access_token
        assert result.value.refresh_token == refresh_token  # below rotation interval

    async def test_refresh_token_invalid(
        self, rdb_session_manager: SessionManager[AsyncSession]
    ) -> None:
        """Refresh fails with invalid refresh token."""
        # Given: nonexistent token
        service = _make_auth_service(rdb_session_manager)

        # When: refresh with invalid token
        result = await service.refresh_token(
            RefreshTokenInput(refresh_token="invalid-token")
        )

        # Then: InvalidRefreshToken
        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidRefreshToken)


class TestAuthServiceLogout:
    """logout tests."""

    @pytest.fixture
    async def session_with_tokens(
        self, rdb_session_manager: SessionManager[AsyncSession]
    ) -> tuple[AuthService, str, str]:
        """Return AuthService with created session + session_id + refresh_token."""
        service = _make_auth_service(rdb_session_manager)
        email = "logout-test@example.com"
        async with rdb_session_manager() as session:
            await UserRepository().create(session, UserCreate(email=email))
        send_output = await service.send_code(SendCodeInput(email=email))
        async with rdb_session_manager() as session:
            verification = await service.email_verification_repo.get_by_email_and_csrf(
                session, email, send_output.csrf_token
            )
        assert verification is not None
        result = await service.verify_code(
            VerifyCodeInput(
                email=email,
                code=verification.code,
                csrf_token=send_output.csrf_token,
            )
        )
        assert isinstance(result, Success)

        # Extract session_id from access_token
        payload = decode_access_token(
            config=_TEST_AUTH_CONFIG.jwt,
            token=result.value.access_token,
        )
        return service, payload.session_id, result.value.refresh_token

    async def test_logout(
        self,
        session_with_tokens: tuple[AuthService, str, str],
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Revoke session."""
        # Given: valid session
        service, session_id, refresh_token = session_with_tokens

        # When: logout
        result = await service.logout(LogoutInput(session_id=session_id))

        # Then: success
        assert isinstance(result, Success)

        # Then: refresh token fails (revoked)
        refresh_result = await service.refresh_token(
            RefreshTokenInput(refresh_token=refresh_token)
        )
        assert isinstance(refresh_result, Failure)
        assert isinstance(refresh_result.error, InvalidRefreshToken)

    async def test_logout_not_found(
        self, rdb_session_manager: SessionManager[AsyncSession]
    ) -> None:
        """Return SessionNotFound when revoking nonexistent session."""
        # Given: nonexistent session
        service = _make_auth_service(rdb_session_manager)

        # When: logout
        result = await service.logout(LogoutInput(session_id="nonexistent"))

        # Then: SessionNotFound
        assert isinstance(result, Failure)
        assert isinstance(result.error, SessionNotFound)
