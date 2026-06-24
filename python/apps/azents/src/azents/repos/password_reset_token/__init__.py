"""Password reset token repository."""

import datetime

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.password_reset_token import (
    RDBPasswordResetToken,
    RDBPasswordResetTokenRedemption,
)

from .data import (
    PasswordResetToken,
    PasswordResetTokenCreate,
    PasswordResetTokenList,
    PasswordResetTokenRedemption,
    PasswordResetTokenRedemptionCreate,
    PasswordResetTokenUnavailable,
)


class PasswordResetTokenRepository:
    """Password reset token CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: PasswordResetTokenCreate,
    ) -> PasswordResetToken:
        """Create Password reset token."""
        rdb_token = RDBPasswordResetToken(
            token_hash=create.token_hash,
            user_id=create.user_id,
            created_by_user_id=create.created_by_user_id,
            expires_at=create.expires_at,
        )
        session.add(rdb_token)
        await session.flush()
        return self._build(rdb_token)

    async def get_by_token_hash(
        self,
        session: AsyncSession,
        token_hash: str,
    ) -> PasswordResetToken | None:
        """Fetch password reset token by token hash."""
        result = await session.execute(
            sa.select(RDBPasswordResetToken).where(
                RDBPasswordResetToken.token_hash == token_hash
            )
        )
        rdb_token = result.scalar_one_or_none()
        if rdb_token is None:
            return None
        return self._build(rdb_token)

    async def list_all(
        self,
        session: AsyncSession,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> PasswordResetTokenList:
        """Fetch Password reset token list."""
        count_result = await session.execute(
            sa.select(sa.func.count()).select_from(RDBPasswordResetToken)
        )
        total = count_result.scalar() or 0

        result = await session.execute(
            sa.select(RDBPasswordResetToken)
            .order_by(RDBPasswordResetToken.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return PasswordResetTokenList(
            items=[self._build(rdb) for rdb in result.scalars().all()],
            total=total,
        )

    async def revoke(
        self,
        session: AsyncSession,
        token_id: str,
        *,
        revoked_at: datetime.datetime,
    ) -> bool:
        """Revoke Password reset token."""
        result = await session.execute(
            sa.update(RDBPasswordResetToken)
            .where(RDBPasswordResetToken.id == token_id)
            .values(revoked_at=revoked_at)
        )
        return (result.rowcount or 0) > 0  # type: ignore[union-attr]

    async def get_available_by_token_hash(
        self,
        session: AsyncSession,
        token_hash: str,
        *,
        now: datetime.datetime,
    ) -> Result[PasswordResetToken, PasswordResetTokenUnavailable]:
        """Fetch usable password reset token."""
        result = await session.execute(
            sa.select(RDBPasswordResetToken).where(
                RDBPasswordResetToken.token_hash == token_hash,
                RDBPasswordResetToken.revoked_at.is_(None),
                RDBPasswordResetToken.used_at.is_(None),
                RDBPasswordResetToken.expires_at > now,
            )
        )
        rdb_token = result.scalar_one_or_none()
        if rdb_token is None:
            return Failure(PasswordResetTokenUnavailable())
        return Success(self._build(rdb_token))

    async def claim_for_redemption(
        self,
        session: AsyncSession,
        token_hash: str,
        *,
        now: datetime.datetime,
    ) -> Result[PasswordResetToken, PasswordResetTokenUnavailable]:
        """Claim password reset token for redeem."""
        result = await session.execute(
            sa.update(RDBPasswordResetToken)
            .where(
                RDBPasswordResetToken.token_hash == token_hash,
                RDBPasswordResetToken.revoked_at.is_(None),
                RDBPasswordResetToken.used_at.is_(None),
                RDBPasswordResetToken.expires_at > now,
            )
            .values(used_at=now)
            .returning(RDBPasswordResetToken)
        )
        rdb_token = result.scalar_one_or_none()
        if rdb_token is None:
            return Failure(PasswordResetTokenUnavailable())
        return Success(self._build(rdb_token))

    async def create_redemption(
        self,
        session: AsyncSession,
        create: PasswordResetTokenRedemptionCreate,
    ) -> PasswordResetTokenRedemption:
        """Create Password reset token redemption record."""
        rdb_redemption = RDBPasswordResetTokenRedemption(
            password_reset_token_id=create.password_reset_token_id,
            user_id=create.user_id,
            ip_address=create.ip_address,
            user_agent=create.user_agent,
            redeemed_at=create.redeemed_at,
        )
        session.add(rdb_redemption)
        await session.flush()
        return self._build_redemption(rdb_redemption)

    async def list_redemptions_by_token_id(
        self,
        session: AsyncSession,
        password_reset_token_id: str,
    ) -> list[PasswordResetTokenRedemption]:
        """Fetch Password reset token redemption record."""
        result = await session.execute(
            sa.select(RDBPasswordResetTokenRedemption)
            .where(
                RDBPasswordResetTokenRedemption.password_reset_token_id
                == password_reset_token_id
            )
            .order_by(RDBPasswordResetTokenRedemption.redeemed_at.asc())
        )
        return [self._build_redemption(rdb) for rdb in result.scalars().all()]

    def _build(self, rdb: RDBPasswordResetToken) -> PasswordResetToken:
        """Convert RDBPasswordResetToken to domain model."""
        return PasswordResetToken(
            id=rdb.id,
            token_hash=rdb.token_hash,
            user_id=rdb.user_id,
            created_by_user_id=rdb.created_by_user_id,
            expires_at=rdb.expires_at,
            used_at=rdb.used_at,
            revoked_at=rdb.revoked_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    def _build_redemption(
        self,
        rdb: RDBPasswordResetTokenRedemption,
    ) -> PasswordResetTokenRedemption:
        """Convert RDBPasswordResetTokenRedemption to domain model."""
        return PasswordResetTokenRedemption(
            id=rdb.id,
            password_reset_token_id=rdb.password_reset_token_id,
            user_id=rdb.user_id,
            ip_address=rdb.ip_address,
            user_agent=rdb.user_agent,
            redeemed_at=rdb.redeemed_at,
        )
