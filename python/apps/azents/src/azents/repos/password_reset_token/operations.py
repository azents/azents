"""Completed password-reset database operations."""

import dataclasses
import datetime
from typing import Annotated

from azcommon.datetime import tznow
from fastapi import Depends
from sqlalchemy.dialects.postgresql import insert

from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.models.password_login import RDBPasswordLogin
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_reset_token import PasswordResetTokenRepository
from azents.repos.password_reset_token.data import (
    PasswordResetToken,
    PasswordResetTokenCreate,
    PasswordResetTokenList,
    PasswordResetTokenRedemptionCreate,
)
from azents.repos.session import SessionRepository
from azents.repos.user import UserRepository


@dataclasses.dataclass(frozen=True)
class ResetPreview:
    """Valid reset identity detached from its completed read."""

    email: str
    expires_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class ResetRedemption:
    """Prepared password/reset intent without application callbacks."""

    token_hash: str
    password_hash: str
    now: datetime.datetime
    ip_address: str | None
    user_agent: str | None


class _RejectedRedemption(Exception):
    """Rollback a claimed group before returning ordinary invalid-token evidence."""


@dataclasses.dataclass(frozen=True)
class PasswordResetOperationRepository:
    """Own reset lifetimes and preserve one atomic redemption group."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    token_repository: Annotated[PasswordResetTokenRepository, Depends()]
    user_repository: Annotated[UserRepository, Depends()]
    password_repository: Annotated[PasswordLoginRepository, Depends()]
    session_repository: Annotated[SessionRepository, Depends()]

    async def create(
        self,
        *,
        user_id: str | None,
        email: str | None,
        token_hash: str,
        created_by_user_id: str | None,
        expires_at: datetime.datetime,
    ) -> PasswordResetToken | None:
        """Resolve the target and complete its token insert atomically."""
        async with self.session_manager() as session:
            user = None
            if user_id is not None:
                user = await self.user_repository.get(session, user_id)
            elif email is not None:
                user = await self.user_repository.get_by_email(session, email)
            if user is None:
                return None
            return await self.token_repository.create(
                session,
                PasswordResetTokenCreate(
                    token_hash=token_hash,
                    user_id=user.id,
                    created_by_user_id=created_by_user_id,
                    expires_at=expires_at,
                ),
            )

    async def list_all(self, *, offset: int, limit: int) -> PasswordResetTokenList:
        """Complete count and page in one read-only operation."""
        async with self.read_session_manager() as session:
            return await self.token_repository.list_all(
                session, offset=offset, limit=limit
            )

    async def preview(
        self, *, token_hash: str, now: datetime.datetime
    ) -> ResetPreview | None:
        """Complete token eligibility and current target email lookup."""
        async with self.read_session_manager() as session:
            result = await self.token_repository.get_available_by_token_hash(
                session, token_hash, now=now
            )
            if not result.success:
                return None
            token = result.value
            user = await self.user_repository.get(session, token.user_id)
            if user is None:
                return None
            return ResetPreview(email=user.primary_email, expires_at=token.expires_at)

    async def redeem(self, *, command: ResetRedemption) -> str | None:
        """Claim, set password, revoke Sessions and record redemption as one group."""
        try:
            async with self.session_manager() as session:
                available = await self.token_repository.get_available_by_token_hash(
                    session, command.token_hash, now=command.now
                )
                if not available.success:
                    return None
                user = await self.user_repository.get(session, available.value.user_id)
                if user is None:
                    return None
                claim = await self.token_repository.claim_for_redemption(
                    session, command.token_hash, now=command.now
                )
                if not claim.success:
                    return None
                token = claim.value
                existing = await self.password_repository.get_by_user_id(
                    session, token.user_id
                )
                if existing is not None:
                    update = await self.password_repository.update_password_hash(
                        session, token.user_id, command.password_hash
                    )
                    if not update.success:
                        raise _RejectedRedemption()
                else:
                    # A uniqueness race must not roll back the claim and restart SQL.
                    prepared = RDBPasswordLogin(
                        user_id=token.user_id, password_hash=command.password_hash
                    )
                    statement = insert(RDBPasswordLogin).values(
                        id=prepared.id,
                        user_id=prepared.user_id,
                        password_hash=prepared.password_hash,
                    )
                    await session.write_session.execute(
                        statement.on_conflict_do_update(
                            constraint=RDBPasswordLogin.UQ_USER_ID,
                            set_={"password_hash": command.password_hash},
                        )
                    )
                await self.session_repository.revoke_all_by_user(session, token.user_id)
                await self.token_repository.create_redemption(
                    session,
                    PasswordResetTokenRedemptionCreate(
                        password_reset_token_id=token.id,
                        user_id=token.user_id,
                        ip_address=command.ip_address,
                        user_agent=command.user_agent,
                        redeemed_at=command.now,
                    ),
                )
                return token.user_id
        except _RejectedRedemption:
            return None

    async def revoke(self, *, token_id: str) -> bool:
        """Capture the revoke clock inside its owned mutation."""
        async with self.session_manager() as session:
            return await self.token_repository.revoke(
                session, token_id, revoked_at=tznow()
            )
