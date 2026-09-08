"""AuthService tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from azcommon.datetime import tznow
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
from azents.repos.auth_operation import AuthOperationRepository
from azents.repos.email_verification import EmailVerificationRepository
from azents.repos.email_verification_operation import (
    EmailVerificationOperationRepository,
)
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import PasswordLoginCreate
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
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
    PasswordLoginInput,
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
        auth_operation_repository=AuthOperationRepository(
            user_repository=UserRepository(),
            user_email_repository=UserEmailRepository(),
            password_login_repository=PasswordLoginRepository(),
            session_repository=SessionRepository(),
            session_manager=session_manager,
        ),
        credential_service=CredentialService(
            session_manager=session_manager,
            providers=[
                PasswordCredentialProvider(),
                EmailCredentialProvider(email_service=resolved_email_service),
            ],
            user_repo=UserRepository(),
        ),
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


class _TransactionAssertingTerminalPublisher:
    """Assert terminal invalidation occurs after Session revocation commits."""

    def __init__(self, observed_session_manager: _ObservedSessionManager) -> None:
        self.observed_session_manager = observed_session_manager
        self.invalidated_session_ids: list[str] = []

    async def publish_runtime_terminal_invalidation(self, runtime_id: str) -> None:
        """Reject unrelated Runtime invalidation in this test."""
        raise AssertionError(runtime_id)

    async def publish_user_terminal_invalidation(self, user_id: str) -> None:
        """Reject unrelated User invalidation in this test."""
        raise AssertionError(user_id)

    async def publish_authentication_session_terminal_invalidation(
        self,
        authentication_session_id: str,
    ) -> None:
        """Record post-commit invalidation."""
        assert not self.observed_session_manager.active
        self.invalidated_session_ids.append(authentication_session_id)

    async def publish_agent_session_terminal_invalidation(
        self,
        agent_session_id: str,
    ) -> None:
        """Reject unrelated Agent Session invalidation in this test."""
        raise AssertionError(agent_session_id)


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

    async def test_verify_code_disabled_user_preserves_invalid_code_mapping(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Disabled existing User remains indistinguishable from invalid OTP."""
        service = _make_auth_service(rdb_session_manager)
        email = "verify-disabled@example.com"
        async with rdb_session_manager() as session:
            user = await UserRepository().create(session, UserCreate(email=email))
            await UserRepository().disable_access(
                session,
                user.id,
                disabled_at=tznow(),
            )
        sent = await service.send_code(SendCodeInput(email=email))
        verification = (
            await service.email_verification_operation_repository.get_by_email_and_csrf(
                email=email,
                csrf_token=sent.csrf_token,
            )
        )
        assert verification is not None

        result = await service.verify_code(
            VerifyCodeInput(
                email=email,
                code=verification.code,
                csrf_token=sent.csrf_token,
            )
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidVerificationCode)

    async def test_verify_code_creates_jwt_after_repository_transaction(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """JWT publication sees no active Auth repository transaction."""
        observed_session_manager = _ObservedSessionManager(rdb_session_manager)
        service = _make_auth_service(observed_session_manager)
        email = "verify-jwt-boundary@example.com"
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
        create_token = Mock(return_value="published-access-token")

        def assert_transaction_closed(**kwargs: object) -> str:
            assert not observed_session_manager.active
            return create_token(**kwargs)

        monkeypatch.setattr(
            "azents.services.auth.create_access_token",
            assert_transaction_closed,
        )

        result = await service.verify_code(
            VerifyCodeInput(
                email=email,
                code=verification.code,
                csrf_token=sent.csrf_token,
            )
        )

        assert isinstance(result, Success)
        assert result.value.access_token == "published-access-token"
        create_token.assert_called_once()

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
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Refresh crypto input and JWT publication run outside the transaction."""
        # Given: create session
        observed_session_manager = _ObservedSessionManager(rdb_session_manager)
        service = _make_auth_service(observed_session_manager)
        _, refresh_token = await self._create_session(service, rdb_session_manager)
        generate_token = Mock(return_value="unused-candidate-token")
        create_token = Mock(return_value="refreshed-access-token")

        def assert_generate_outside_transaction() -> str:
            assert not observed_session_manager.active
            return generate_token()

        def assert_jwt_outside_transaction(**kwargs: object) -> str:
            assert not observed_session_manager.active
            return create_token(**kwargs)

        monkeypatch.setattr(
            "azents.services.auth.generate_refresh_token",
            assert_generate_outside_transaction,
        )
        monkeypatch.setattr(
            "azents.services.auth.create_access_token",
            assert_jwt_outside_transaction,
        )

        # When: refresh token
        result = await service.refresh_token(
            RefreshTokenInput(refresh_token=refresh_token)
        )

        # Then: success (return existing token because below rotation interval)
        assert isinstance(result, Success)
        assert result.value.access_token == "refreshed-access-token"
        assert result.value.refresh_token == refresh_token  # below rotation interval
        generate_token.assert_called_once()
        create_token.assert_called_once()

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

    async def test_logout_invalidates_terminal_after_repository_transaction(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Terminal invalidation runs after the revoke transaction completes."""
        observed_session_manager = _ObservedSessionManager(rdb_session_manager)
        service = _make_auth_service(observed_session_manager)
        email = "logout-boundary@example.com"
        async with rdb_session_manager() as session:
            user = await UserRepository().create(session, UserCreate(email=email))
            authentication_session = await SessionRepository().create(
                session,
                SessionCreate(
                    user_id=user.id,
                    refresh_token="logout-boundary-refresh",
                    expires_at=tznow() + datetime.timedelta(hours=1),
                ),
            )
        publisher = _TransactionAssertingTerminalPublisher(observed_session_manager)
        service.terminal_invalidation_publisher = publisher

        result = await service.logout(LogoutInput(session_id=authentication_session.id))

        assert isinstance(result, Success)
        assert publisher.invalidated_session_ids == [authentication_session.id]


class TestAuthServicePasswordLogin:
    """Password login transaction boundary tests."""

    async def test_password_crypto_and_jwt_run_outside_database_transaction(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Password verification and JWT creation see completed DB operations."""
        observed_session_manager = _ObservedSessionManager(rdb_session_manager)
        service = _make_auth_service(observed_session_manager)
        email = "password-boundary@example.com"
        async with rdb_session_manager() as session:
            user = await UserRepository().create(session, UserCreate(email=email))
            await PasswordLoginRepository().create(
                session,
                PasswordLoginCreate(
                    user_id=user.id,
                    password_hash="stored-password-hash",
                ),
            )
        verify = Mock(return_value=True)
        generate_token = Mock(return_value="password-boundary-refresh-token")
        create_token = Mock(return_value="password-access-token")

        def assert_verify_outside_transaction(
            password: str,
            password_hash: str,
        ) -> bool:
            assert not observed_session_manager.active
            return verify(password, password_hash)

        def assert_jwt_outside_transaction(**kwargs: object) -> str:
            assert not observed_session_manager.active
            return create_token(**kwargs)

        def assert_generate_outside_transaction() -> str:
            assert not observed_session_manager.active
            return generate_token()

        monkeypatch.setattr(
            "azents.services.auth.verify_password",
            assert_verify_outside_transaction,
        )
        monkeypatch.setattr(
            "azents.services.auth.create_access_token",
            assert_jwt_outside_transaction,
        )
        monkeypatch.setattr(
            "azents.services.auth.generate_refresh_token",
            assert_generate_outside_transaction,
        )

        result = await service.login_with_password(
            PasswordLoginInput(
                email=email,
                password="plaintext-password",
            )
        )

        assert isinstance(result, Success)
        assert result.value.access_token == "password-access-token"
        verify.assert_called_once_with(
            "plaintext-password",
            "stored-password-hash",
        )
        generate_token.assert_called_once()
        create_token.assert_called_once()
