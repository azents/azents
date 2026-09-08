"""AuthService tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from azents.repos.email_verification_operation import (
    EmailVerificationOperationRepository,
)
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
from azents.services.runtime_terminal.invalidation import (
    NoopRuntimeTerminalInvalidationPublisher,
)

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
    *,
    email_service: EmailService | None = None,
) -> AuthService:
    """Create AuthService for tests."""
    resolved_email_service = email_service or _make_email_service()
    return AuthService(
        email_service=resolved_email_service,
        email_verification_operation_repository=EmailVerificationOperationRepository(
            email_verification_repository=EmailVerificationRepository(),
            session_manager=session_manager,
        ),
        password_login_repo=PasswordLoginRepository(),
        user_repo=UserRepository(),
        user_email_repo=UserEmailRepository(),
        session_repo=SessionRepository(),
        credential_service=CredentialService(
            session_manager=session_manager,
            providers=[
                PasswordCredentialProvider(),
                EmailCredentialProvider(email_service=resolved_email_service),
            ],
            user_repo=UserRepository(),
        ),
        session_manager=session_manager,
        terminal_invalidation_publisher=NoopRuntimeTerminalInvalidationPublisher(),
        auth_config=_TEST_AUTH_CONFIG,
        email_config=None,
    )


class _ObservedSessionManager:
    """Record whether a repository-owned database operation is active."""

    def __init__(self, delegate: SessionManager[AsyncSession]) -> None:
        self.delegate = delegate
        self.active = False

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        self.active = True
        try:
            async with self.delegate() as session:
                yield session
        finally:
            self.active = False


class _TransactionAssertingEmailService(EmailService):
    """Assert delivery occurs after the operation repository closes its session."""

    def __init__(self, observed_session_manager: _ObservedSessionManager) -> None:
        super().__init__(config=None, ses_client=None)
        self.observed_session_manager = observed_session_manager
        self.delivery_count = 0

    async def send_verification_code(
        self,
        *,
        to_email: str,
        code: str,
        expire_minutes: int,
        language: str = "ko",
    ) -> None:
        """Record delivery only after the database operation has completed."""
        del to_email, code, expire_minutes, language
        assert not self.observed_session_manager.active
        self.delivery_count += 1


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

    async def test_send_code_delivers_email_after_repository_transaction(
        self, rdb_session_manager: SessionManager[AsyncSession]
    ) -> None:
        """SMTP delivery sees no active database transaction."""
        observed_session_manager = _ObservedSessionManager(rdb_session_manager)
        email_service = _TransactionAssertingEmailService(observed_session_manager)
        service = _make_auth_service(
            observed_session_manager,
            email_service=email_service,
        )

        await service.send_code(SendCodeInput(email="post-commit@example.com"))

        assert email_service.delivery_count == 1


class TestAuthServiceVerifyCode:
    """verify_code tests."""

    async def test_verify_code_new_user_requires_signup_token(
        self, rdb_session_manager: SessionManager[AsyncSession]
    ) -> None:
        """New email verification does not create User without signup token."""
        service = _make_auth_service(rdb_session_manager)
        email = "verify-new@example.com"
        send_output = await service.send_code(SendCodeInput(email=email))

        verification = (
            await service.email_verification_operation_repository.get_by_email_and_csrf(
                email=email,
                csrf_token=send_output.csrf_token,
            )
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
        v2 = (
            await service.email_verification_operation_repository.get_by_email_and_csrf(
                email=email,
                csrf_token=send2.csrf_token,
            )
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

    async def test_verify_code_duplicate_returns_existing_invalid_code_error(
        self, rdb_session_manager: SessionManager[AsyncSession]
    ) -> None:
        """A second completed verification preserves the invalid-code result."""
        service = _make_auth_service(rdb_session_manager)
        email = "verify-duplicate@example.com"
        async with rdb_session_manager() as session:
            await UserRepository().create(session, UserCreate(email=email))
        sent = await service.send_code(SendCodeInput(email=email))
        verification = (
            await service.email_verification_operation_repository.get_by_email_and_csrf(
                email=email,
                csrf_token=sent.csrf_token,
            )
        )
        assert verification is not None
        input_data = VerifyCodeInput(
            email=email,
            code=verification.code,
            csrf_token=sent.csrf_token,
        )

        first = await service.verify_code(input_data)
        duplicate = await service.verify_code(input_data)

        assert isinstance(first, Success)
        assert isinstance(duplicate, Failure)
        assert isinstance(duplicate.error, InvalidVerificationCode)


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
        verification = (
            await service.email_verification_operation_repository.get_by_email_and_csrf(
                email=email,
                csrf_token=send_output.csrf_token,
            )
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
        verification = (
            await service.email_verification_operation_repository.get_by_email_and_csrf(
                email=email,
                csrf_token=send_output.csrf_token,
            )
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
        service.terminal_invalidation_publisher = AsyncMock()

        # When: logout
        result = await service.logout(LogoutInput(session_id=session_id))

        # Then: success
        assert isinstance(result, Success)
        publisher = service.terminal_invalidation_publisher
        publish = publisher.publish_authentication_session_terminal_invalidation
        publish.assert_awaited_once_with(session_id)

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
