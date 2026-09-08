"""Completed database operations for authentication Sessions."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.session import SessionRepository
from azents.repos.session.data import NotFound, Session, SessionCreate, TokenMatch
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.user_email import UserEmailRepository

from .data import (
    AuthenticationUnavailable,
    PasswordCredentialLookup,
    PasswordCredentialSnapshot,
    RefreshAuthenticationSession,
    RefreshTokenRejected,
    RegistrationRequired,
    ResolvedAuthUser,
    VerifiedEmailUserResolve,
)


@dataclasses.dataclass
class AuthOperationRepository:
    """Own completed database-only authentication Session operations."""

    user_repository: Annotated[UserRepository, Depends(UserRepository)]
    user_email_repository: Annotated[UserEmailRepository, Depends(UserEmailRepository)]
    password_login_repository: Annotated[
        PasswordLoginRepository, Depends(PasswordLoginRepository)
    ]
    session_repository: Annotated[SessionRepository, Depends(SessionRepository)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def resolve_verified_email_user(
        self,
        *,
        resolve: VerifiedEmailUserResolve,
    ) -> Result[
        ResolvedAuthUser,
        RegistrationRequired | AuthenticationUnavailable,
    ]:
        """Resolve or create the User for a successfully verified email."""
        async with self.session_manager() as session:
            user_email = await self.user_email_repository.get_by_email(
                session,
                resolve.email,
            )
            if user_email is None:
                if not resolve.registration_open:
                    return Failure(RegistrationRequired())
                user = await self.user_repository.create(
                    session,
                    UserCreate(email=resolve.email),
                )
                return Success(ResolvedAuthUser(user_id=user.id))

            user = await self.user_repository.get(session, user_email.user_id)
            if user is not None and user.access_disabled_at is not None:
                return Failure(AuthenticationUnavailable())
            return Success(ResolvedAuthUser(user_id=user_email.user_id))

    async def get_password_credential(
        self,
        *,
        lookup: PasswordCredentialLookup,
    ) -> Result[PasswordCredentialSnapshot, AuthenticationUnavailable]:
        """Load an active User password credential as detached data."""
        async with self.session_manager() as session:
            user = await self.user_repository.get_by_email(session, lookup.email)
            if user is None or user.access_disabled_at is not None:
                return Failure(AuthenticationUnavailable())

            password_login = await self.password_login_repository.get_by_user_id(
                session,
                user.id,
            )
            if password_login is None:
                return Failure(AuthenticationUnavailable())
            return Success(
                PasswordCredentialSnapshot(
                    user_id=user.id,
                    password_hash=password_login.password_hash,
                )
            )

    async def issue_session(
        self,
        *,
        create: SessionCreate,
    ) -> Result[Session, AuthenticationUnavailable]:
        """Create a Session only while the User remains active."""
        async with self.session_manager() as session:
            result = await self.session_repository.create_for_active_user(
                session,
                create,
            )
            match result:
                case Success(created_session):
                    return Success(created_session)
                case Failure():
                    return Failure(AuthenticationUnavailable())
                case _:
                    assert_never(result)

    async def refresh_session(
        self,
        *,
        refresh: RefreshAuthenticationSession,
    ) -> Result[Session, RefreshTokenRejected]:
        """Validate and refresh one authentication Session atomically."""
        async with self.session_manager() as session:
            matched = await self.session_repository.get_by_refresh_token(
                session,
                refresh.refresh_token,
            )
            if matched is None:
                return Failure(RefreshTokenRejected())

            authentication_session, token_match = matched
            eligibility_now = tznow()
            if (
                authentication_session.revoked_at is not None
                or authentication_session.expires_at <= eligibility_now
            ):
                return Failure(RefreshTokenRejected())

            user = await self.user_repository.get(
                session,
                authentication_session.user_id,
            )
            if user is None or user.access_disabled_at is not None:
                return Failure(RefreshTokenRejected())

            refresh_now = tznow()
            token_age = refresh_now - authentication_session.refresh_token_created_at
            if token_match == TokenMatch.PREVIOUS:
                if token_age > refresh.grace_period:
                    return Failure(RefreshTokenRejected())
                return Success(authentication_session)

            if token_match == TokenMatch.CURRENT:
                if token_age < refresh.rotation_period:
                    return Success(authentication_session)
                rotate_result = await self.session_repository.rotate_refresh_token(
                    session,
                    authentication_session.id,
                    authentication_session.refresh_token,
                    refresh.candidate_refresh_token,
                    refresh_now + refresh.expire_timedelta,
                )
                match rotate_result:
                    case Success(updated_session):
                        return Success(updated_session)
                    case Failure(error) if isinstance(error, NotFound):
                        return Failure(RefreshTokenRejected())
                    case Failure(error):
                        assert_never(error)
                    case _:
                        assert_never(rotate_result)

            assert_never(token_match)

    async def revoke_session(
        self,
        *,
        session_id: str,
    ) -> Result[Session, NotFound]:
        """Revoke one Session in a completed database operation."""
        async with self.session_manager() as session:
            return await self.session_repository.revoke(session, session_id)
