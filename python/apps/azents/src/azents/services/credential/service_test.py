"""CredentialService tests."""

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import EmailConfig
from azents.core.email.service import EmailService
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import PasswordLoginCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services.credential.data import (
    CredentialType,
    CredentialUnavailableReason,
)
from azents.services.credential.providers import (
    EmailCredentialProvider,
    PasswordCredentialProvider,
)
from azents.services.credential.service import CredentialService


def _make_email_service(*, configured: bool) -> EmailService:
    """Create EmailService for tests."""
    if not configured:
        return EmailService(config=None, ses_client=None)
    return EmailService(
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


def _make_service(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    email_configured: bool,
) -> CredentialService:
    """Create CredentialService for tests."""
    email_service = _make_email_service(configured=email_configured)
    return CredentialService(
        session_manager=rdb_session_manager,
        providers=[
            PasswordCredentialProvider(),
            EmailCredentialProvider(email_service=email_service),
        ],
        user_repo=UserRepository(),
    )


class TestCredentialService:
    """CredentialService tests."""

    async def test_verified_email_requires_smtp_for_validity(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Verified email is valid credential only when SMTP is configured."""
        async with rdb_session_manager() as session:
            user = await UserRepository().create_with_verified_primary_email(
                session,
                UserCreate(email="email-only@example.com"),
                verified_at=datetime.datetime.now(datetime.UTC),
            )

        service = _make_service(rdb_session_manager, email_configured=False)

        summaries = await service.get_user_credentials(user_id=user.id)

        assert summaries is not None
        email = next(
            summary for summary in summaries if summary.type == CredentialType.EMAIL
        )
        assert email.configured
        assert not email.valid
        assert (
            email.unavailable_reason == CredentialUnavailableReason.SMTP_NOT_CONFIGURED
        )

    async def test_password_only_user_cannot_remove_last_valid_credential(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Password cannot be removed when it is the only valid credential."""
        async with rdb_session_manager() as session:
            user = await UserRepository().create_with_verified_primary_email(
                session,
                UserCreate(email="password-only@example.com"),
                verified_at=datetime.datetime.now(datetime.UTC),
            )
            await PasswordLoginRepository().create(
                session,
                PasswordLoginCreate(user_id=user.id, password_hash="hash"),
            )

        service = _make_service(rdb_session_manager, email_configured=False)

        check = await service.check_remove_allowed(
            user_id=user.id,
            credential_type=CredentialType.PASSWORD,
        )

        assert check is not None
        assert not check.allowed
        assert check.reason == CredentialUnavailableReason.LAST_VALID_CREDENTIAL

    async def test_password_can_be_removed_when_verified_email_is_valid(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Password can be removed when SMTP configured + verified email exists."""
        async with rdb_session_manager() as session:
            user = await UserRepository().create_with_verified_primary_email(
                session,
                UserCreate(email="two-credentials@example.com"),
                verified_at=datetime.datetime.now(datetime.UTC),
            )
            await PasswordLoginRepository().create(
                session,
                PasswordLoginCreate(user_id=user.id, password_hash="hash"),
            )

        service = _make_service(rdb_session_manager, email_configured=True)

        check = await service.check_remove_allowed(
            user_id=user.id,
            credential_type=CredentialType.PASSWORD,
        )

        assert check is not None
        assert check.allowed
        assert check.reason is None

    async def test_login_projection_keeps_public_shape_minimal(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Public login projection returns only minimal information."""
        async with rdb_session_manager() as session:
            user = await UserRepository().create_with_verified_primary_email(
                session,
                UserCreate(email="login-method@example.com"),
                verified_at=datetime.datetime.now(datetime.UTC),
            )
            await PasswordLoginRepository().create(
                session,
                PasswordLoginCreate(user_id=user.id, password_hash="hash"),
            )

        service = _make_service(rdb_session_manager, email_configured=True)

        projection = await service.get_login_projection(
            email="login-method@example.com"
        )

        assert projection.has_password
        assert projection.email_available

    async def test_login_projection_does_not_require_existing_email_for_email_flow(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Email flow availability does not require user existence."""
        service = _make_service(rdb_session_manager, email_configured=True)

        projection = await service.get_login_projection(email="unknown@example.com")

        assert not projection.has_password
        assert projection.email_available
