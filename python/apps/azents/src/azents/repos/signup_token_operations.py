"""Completed Signup token database groups with atomic account redemption."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.signup_token_operations import (
    InvalidSignupToken,
    SignupTokenEmailAlreadyRegistered,
    SignupTokenEmailMismatch,
    SignupTokenRedeemCommand,
    SignupTokenRedeemFacts,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import PasswordLoginCreate
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.signup_token import SignupTokenRepository
from azents.repos.signup_token.data import (
    SignupToken,
    SignupTokenCreate,
    SignupTokenList,
    SignupTokenRedemptionCreate,
    SignupTokenUnavailable,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.user_email import UserEmailRepository


@dataclasses.dataclass(frozen=True)
class SignupTokenOperationRepository:
    """Own original groups without application preparation or post-commit effects."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    signup_token_repository: Annotated[
        SignupTokenRepository, Depends(SignupTokenRepository)
    ]
    user_repository: Annotated[UserRepository, Depends(UserRepository)]
    user_email_repository: Annotated[UserEmailRepository, Depends(UserEmailRepository)]
    password_login_repository: Annotated[
        PasswordLoginRepository, Depends(PasswordLoginRepository)
    ]
    session_repository: Annotated[SessionRepository, Depends(SessionRepository)]

    async def create(self, *, create: SignupTokenCreate) -> SignupToken:
        """Complete one prepared token insert before metadata/plaintext projection."""
        async with self.session_manager() as session:
            return await self.signup_token_repository.create(session, create)

    async def list_all(self, *, offset: int, limit: int) -> SignupTokenList:
        """Keep original count and ordered page together in one completed group."""
        async with self.session_manager() as session:
            return await self.signup_token_repository.list_all(
                session, offset=offset, limit=limit
            )

    async def get_by_token_hash(self, *, token_hash: str) -> SignupToken | None:
        """Complete exact token lookup before application preview predicates."""
        async with self.session_manager() as session:
            return await self.signup_token_repository.get_by_token_hash(
                session, token_hash
            )

    async def redeem(
        self, *, command: SignupTokenRedeemCommand
    ) -> Result[
        SignupTokenRedeemFacts,
        InvalidSignupToken
        | SignupTokenEmailMismatch
        | SignupTokenEmailAlreadyRegistered,
    ]:
        """Retain claim, verified account, password, Session and audit atomically."""
        async with self.session_manager() as session:
            available_result = (
                await self.signup_token_repository.get_available_by_token_hash(
                    session, command.token_hash, now=command.now
                )
            )
            if available_result.success:
                token = available_result.value
            else:
                error = available_result.error
                match error:
                    case SignupTokenUnavailable():
                        return Failure(InvalidSignupToken())
                    case _:
                        assert_never(error)

            if token.email != command.email:
                return Failure(SignupTokenEmailMismatch())

            existing_email = await self.user_email_repository.get_by_email(
                session, command.email
            )
            if existing_email is not None:
                return Failure(SignupTokenEmailAlreadyRegistered(email=command.email))

            claim_result = await self.signup_token_repository.claim_for_redemption(
                session, command.token_hash, now=command.now
            )
            if claim_result.success:
                token = claim_result.value
            else:
                error = claim_result.error
                match error:
                    case SignupTokenUnavailable():
                        return Failure(InvalidSignupToken())
                    case _:
                        assert_never(error)

            user = await self.user_repository.create_with_verified_primary_email(
                session,
                UserCreate(email=command.email),
                verified_at=command.now,
            )
            password_create_result = await self.password_login_repository.create(
                session,
                PasswordLoginCreate(
                    user_id=user.id, password_hash=command.password_hash
                ),
            )
            match password_create_result:
                case Success():
                    pass
                case Failure():
                    # The narrow primitive has rolled back the complete group.
                    return Failure(
                        SignupTokenEmailAlreadyRegistered(email=command.email)
                    )
                case _:
                    assert_never(password_create_result)

            db_session = await self.session_repository.create(
                session,
                SessionCreate(
                    user_id=user.id,
                    refresh_token=command.refresh_token,
                    expires_at=command.expires_at,
                    max_expires_at=command.max_expires_at,
                    user_agent=command.user_agent,
                    ip_address=command.ip_address,
                ),
            )
            await self.signup_token_repository.create_redemption(
                session,
                SignupTokenRedemptionCreate(
                    signup_token_id=token.id,
                    user_id=user.id,
                    email=command.email,
                    ip_address=command.ip_address,
                    user_agent=command.user_agent,
                    redeemed_at=command.now,
                ),
            )
            return Success(
                SignupTokenRedeemFacts(user_id=user.id, session_id=db_session.id)
            )

    async def revoke(self, *, token_id: str) -> bool:
        """Sample revoke time in the owned scope and preserve repeated-row updates."""
        async with self.session_manager() as session:
            return await self.signup_token_repository.revoke(
                session, token_id, revoked_at=tznow()
            )
