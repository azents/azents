"""Signup token service."""

import dataclasses
import hashlib
import secrets
from typing import Annotated, assert_never

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.auth.jwt import create_access_token
from azents.core.auth.password import (
    WeakPasswordError,
    hash_password,
    validate_password_strength,
)
from azents.core.config import AuthConfig, Config
from azents.core.deps import get_auth_config, get_config
from azents.core.email.service import EmailService
from azents.core.enums import SignupTokenDeliveryMethod
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import PasswordLoginCreate
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.signup_token import SignupTokenRepository
from azents.repos.signup_token.data import (
    SignupTokenCreate,
    SignupTokenRedemptionCreate,
    SignupTokenUnavailable,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.user_email import UserEmailRepository
from azents.services._utils import generate_refresh_token

from .data import (
    CreateSignupTokenInput,
    InvalidSignupToken,
    PreviewSignupTokenInput,
    PreviewSignupTokenOutput,
    RedeemSignupTokenInput,
    RedeemSignupTokenOutput,
    SignupEmailDeliveryUnavailable,
    SignupTokenEmailAlreadyRegistered,
    SignupTokenEmailMismatch,
    SignupTokenListOutput,
    SignupTokenOutput,
    SignupTokenWithPlaintextOutput,
    WeakSignupPassword,
)

_SIGNUP_TOKEN_BYTES = 32


def normalize_signup_email(email: str) -> str:
    """Normalize Signup token email."""
    return email.strip().lower()


def generate_signup_token() -> str:
    """Create plaintext Signup token."""
    return secrets.token_urlsafe(_SIGNUP_TOKEN_BYTES)


def hash_signup_token(token: str) -> str:
    """Hash plaintext Signup token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mask_signup_email(email: str) -> str:
    """Create email hint for Signup token preview."""
    local, separator, domain = email.partition("@")
    if separator == "":
        return "***"
    local_hint = f"{local[:1]}***" if local else "***"
    return f"{local_hint}@{domain}"


@dataclasses.dataclass
class SignupTokenService:
    """Signup token service."""

    signup_token_repo: Annotated[SignupTokenRepository, Depends()]
    user_repo: Annotated[UserRepository, Depends()]
    user_email_repo: Annotated[UserEmailRepository, Depends()]
    password_login_repo: Annotated[PasswordLoginRepository, Depends()]
    session_repo: Annotated[SessionRepository, Depends()]
    email_service: Annotated[EmailService, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    auth_config: Annotated[AuthConfig, Depends(get_auth_config)]
    config: Annotated[Config, Depends(get_config)]

    async def create(
        self,
        input: CreateSignupTokenInput,
    ) -> SignupTokenWithPlaintextOutput:
        """Create Signup token.

        :param input: Create input
        :return: Create output including plaintext token
        """
        plaintext_token = generate_signup_token()
        token_hash = hash_signup_token(plaintext_token)
        now = tznow()
        expires_at = input.expires_at or (
            now + self.auth_config.signup_token.default_expire_timedelta
        )
        max_uses = input.max_uses or self.auth_config.signup_token.default_max_uses

        async with self.session_manager() as session:
            token = await self.signup_token_repo.create(
                session,
                SignupTokenCreate(
                    token_hash=token_hash,
                    email=normalize_signup_email(input.email),
                    created_by_user_id=input.created_by_user_id,
                    delivery_method=input.delivery_method,
                    expires_at=expires_at,
                    max_uses=max_uses,
                ),
            )

        return SignupTokenWithPlaintextOutput(
            token=SignupTokenOutput.convert_from(token),
            plaintext_token=plaintext_token,
        )

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> SignupTokenListOutput:
        """Fetch Signup token list.

        :param offset: Record count to skip
        :param limit: Maximum return count
        :return: signup token list
        """
        async with self.session_manager() as session:
            result = await self.signup_token_repo.list_all(
                session,
                offset=offset,
                limit=limit,
            )
        return SignupTokenListOutput(
            items=[SignupTokenOutput.convert_from(token) for token in result.items],
            total=result.total,
        )

    async def preview(
        self,
        input: PreviewSignupTokenInput,
    ) -> PreviewSignupTokenOutput:
        """Preview Signup token status.

        :param input: preview input
        :return: token preview
        """
        token_hash = hash_signup_token(input.token)
        now = tznow()
        async with self.session_manager() as session:
            token = await self.signup_token_repo.get_by_token_hash(session, token_hash)

        if token is None:
            return PreviewSignupTokenOutput(valid=False, email=None, expires_at=None)
        if token.revoked_at is not None:
            return PreviewSignupTokenOutput(valid=False, email=None, expires_at=None)
        if token.expires_at <= now:
            return PreviewSignupTokenOutput(valid=False, email=None, expires_at=None)
        if token.used_count >= token.max_uses:
            return PreviewSignupTokenOutput(valid=False, email=None, expires_at=None)
        return PreviewSignupTokenOutput(
            valid=True,
            email=mask_signup_email(token.email),
            expires_at=token.expires_at,
        )

    async def redeem(
        self,
        input: RedeemSignupTokenInput,
    ) -> Result[
        RedeemSignupTokenOutput,
        InvalidSignupToken
        | SignupTokenEmailMismatch
        | SignupTokenEmailAlreadyRegistered
        | WeakSignupPassword,
    ]:
        """Create account with Signup token and issue session.

        :param input: redeem input
        :return: token response on success, error on failure
        """
        try:
            validate_password_strength(input.password)
        except WeakPasswordError as error:
            return Failure(WeakSignupPassword(message=error.message))

        token_hash = hash_signup_token(input.token)
        now = tznow()
        email = normalize_signup_email(input.email)
        password_hash = hash_password(input.password)
        refresh_token = generate_refresh_token()
        expires_at = now + self.auth_config.refresh_token.expire_timedelta
        max_expires_at = (
            now + self.auth_config.refresh_token.max_expire_timedelta
            if self.auth_config.refresh_token.max_expire_timedelta is not None
            else None
        )

        async with self.session_manager() as session:
            available_result = await self.signup_token_repo.get_available_by_token_hash(
                session,
                token_hash,
                now=now,
            )
            match available_result:
                case Success(token):
                    pass
                case Failure(error):
                    match error:
                        case SignupTokenUnavailable():
                            return Failure(InvalidSignupToken())
                        case _:
                            assert_never(error)
                case _:
                    assert_never(available_result)

            if token.email != email:
                return Failure(SignupTokenEmailMismatch())

            existing_email = await self.user_email_repo.get_by_email(session, email)
            if existing_email is not None:
                return Failure(SignupTokenEmailAlreadyRegistered(email=email))

            claim_result = await self.signup_token_repo.claim_for_redemption(
                session,
                token_hash,
                now=now,
            )
            match claim_result:
                case Success(token):
                    pass
                case Failure(error):
                    match error:
                        case SignupTokenUnavailable():
                            return Failure(InvalidSignupToken())
                        case _:
                            assert_never(error)
                case _:
                    assert_never(claim_result)

            user = await self.user_repo.create_with_verified_primary_email(
                session,
                UserCreate(email=email),
                verified_at=now,
            )
            password_create_result = await self.password_login_repo.create(
                session,
                PasswordLoginCreate(
                    user_id=user.id,
                    password_hash=password_hash,
                ),
            )
            match password_create_result:
                case Success():
                    pass
                case Failure():
                    return Failure(SignupTokenEmailAlreadyRegistered(email=email))
                case _:
                    assert_never(password_create_result)

            db_session = await self.session_repo.create(
                session,
                SessionCreate(
                    user_id=user.id,
                    refresh_token=refresh_token,
                    expires_at=expires_at,
                    max_expires_at=max_expires_at,
                    user_agent=input.user_agent,
                    ip_address=input.ip_address,
                ),
            )
            await self.signup_token_repo.create_redemption(
                session,
                SignupTokenRedemptionCreate(
                    signup_token_id=token.id,
                    user_id=user.id,
                    email=email,
                    ip_address=input.ip_address,
                    user_agent=input.user_agent,
                    redeemed_at=now,
                ),
            )

        access_token = create_access_token(
            config=self.auth_config.jwt,
            user_id=user.id,
            session_id=db_session.id,
        )
        return Success(
            RedeemSignupTokenOutput(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=self.auth_config.jwt.access_token_expire_seconds,
            )
        )

    async def revoke(self, token_id: str) -> bool:
        """Revoke Signup token.

        :param token_id: signup token ID
        :return: True when token exists
        """
        async with self.session_manager() as session:
            return await self.signup_token_repo.revoke(
                session,
                token_id,
                revoked_at=tznow(),
            )

    async def create_email_delivery_token(
        self,
        email: str,
    ) -> Result[SignupTokenWithPlaintextOutput, SignupEmailDeliveryUnavailable]:
        """Create and send signup token for email delivery.

        :param email: Email to fix to token
        :return: Created token or delivery unavailable
        """
        if not self.email_service.configured:
            return Failure(SignupEmailDeliveryUnavailable())

        created = await self.create(
            CreateSignupTokenInput(
                email=email,
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.EMAIL,
                expires_at=None,
                max_uses=None,
            )
        )
        signup_url = self.build_signup_url(created.plaintext_token)
        sent = await self.email_service.send_signup_token(
            to_email=created.token.email,
            signup_url=signup_url,
            expire_hours=self.auth_config.signup_token.default_expire_hours,
        )
        if not sent:
            return Failure(SignupEmailDeliveryUnavailable())
        return Success(created)

    async def create_manual_token_for_email(
        self,
        email: str,
        *,
        created_by_user_id: str | None,
    ) -> SignupTokenWithPlaintextOutput:
        """Create signup token for manual delivery.

        :param email: Email to fix to token
        :param created_by_user_id: Creator User ID
        :return: Create output including plaintext token
        """
        return await self.create(
            CreateSignupTokenInput(
                email=email,
                created_by_user_id=created_by_user_id,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=None,
                max_uses=None,
            )
        )

    def build_signup_url(self, token: str) -> str:
        """Create Signup URL."""
        path = f"/signup?token={token}"
        if self.config.web_url:
            return f"{self.config.web_url}{path}"
        return path
