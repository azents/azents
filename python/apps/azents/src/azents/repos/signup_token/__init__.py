"""Signup token repository."""

import datetime

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.signup_token import (
    RDBSignupToken,
    RDBSignupTokenRedemption,
)

from .data import (
    SignupToken,
    SignupTokenCreate,
    SignupTokenList,
    SignupTokenRedemption,
    SignupTokenRedemptionCreate,
    SignupTokenUnavailable,
)


class SignupTokenRepository:
    """Signup token CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: SignupTokenCreate,
    ) -> SignupToken:
        """Create Signup token.

        :param session: Database session
        :param create: Create data
        :return: Created signup token
        """
        rdb_token = RDBSignupToken(
            token_hash=create.token_hash,
            email=create.email,
            created_by_user_id=create.created_by_user_id,
            delivery_method=create.delivery_method,
            expires_at=create.expires_at,
            max_uses=create.max_uses,
        )
        session.add(rdb_token)
        await session.flush()
        return self._build(rdb_token)

    async def get_by_token_hash(
        self,
        session: AsyncSession,
        token_hash: str,
    ) -> SignupToken | None:
        """Fetch signup token by token hash.

        :param session: Database session
        :param token_hash: Hash of original token
        :return: signup token or None
        """
        rdb_token = await self._get_rdb_by_token_hash(session, token_hash)
        if rdb_token is None:
            return None
        return self._build(rdb_token)

    async def list_all(
        self,
        session: AsyncSession,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> SignupTokenList:
        """Fetch Signup token list.

        :param session: Database session
        :param offset: Record count to skip
        :param limit: Maximum return count
        :return: signup token list
        """
        count_result = await session.execute(
            sa.select(sa.func.count()).select_from(RDBSignupToken)
        )
        total = count_result.scalar() or 0

        result = await session.execute(
            sa.select(RDBSignupToken)
            .order_by(RDBSignupToken.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return SignupTokenList(
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
        """Revoke Signup token.

        :param session: Database session
        :param token_id: signup token ID
        :param revoked_at: Revocation time
        :return: True when token exists
        """
        result = await session.execute(
            sa.update(RDBSignupToken)
            .where(RDBSignupToken.id == token_id)
            .values(revoked_at=revoked_at)
        )
        return (result.rowcount or 0) > 0  # type: ignore[union-attr]

    async def get_available_by_token_hash(
        self,
        session: AsyncSession,
        token_hash: str,
        *,
        now: datetime.datetime,
    ) -> Result[SignupToken, SignupTokenUnavailable]:
        """Fetch usable signup token.

        :param session: Database session
        :param token_hash: Hash of original token
        :param now: Current time
        :return: Usable signup token or unusable error
        """
        result = await session.execute(
            sa.select(RDBSignupToken).where(
                RDBSignupToken.token_hash == token_hash,
                RDBSignupToken.revoked_at.is_(None),
                RDBSignupToken.expires_at > now,
                RDBSignupToken.used_count < RDBSignupToken.max_uses,
            )
        )
        rdb_token = result.scalar_one_or_none()
        if rdb_token is None:
            return Failure(SignupTokenUnavailable())
        return Success(self._build(rdb_token))

    async def claim_for_redemption(
        self,
        session: AsyncSession,
        token_hash: str,
        *,
        now: datetime.datetime,
    ) -> Result[SignupToken, SignupTokenUnavailable]:
        """Claim signup token use count for redeem.

        :param session: Database session
        :param token_hash: Hash of original token
        :param now: Current time
        :return: Claimed signup token or unusable error
        """
        result = await session.execute(
            sa.update(RDBSignupToken)
            .where(
                RDBSignupToken.token_hash == token_hash,
                RDBSignupToken.revoked_at.is_(None),
                RDBSignupToken.expires_at > now,
                RDBSignupToken.used_count < RDBSignupToken.max_uses,
            )
            .values(used_count=RDBSignupToken.used_count + 1)
            .returning(RDBSignupToken)
        )
        rdb_token = result.scalar_one_or_none()
        if rdb_token is None:
            return Failure(SignupTokenUnavailable())
        return Success(self._build(rdb_token))

    async def list_redemptions_by_token_id(
        self,
        session: AsyncSession,
        signup_token_id: str,
    ) -> list[SignupTokenRedemption]:
        """Fetch usage records for Signup token.

        :param session: Database session
        :param signup_token_id: signup token ID
        :return: Usage record list
        """
        result = await session.execute(
            sa.select(RDBSignupTokenRedemption)
            .where(RDBSignupTokenRedemption.signup_token_id == signup_token_id)
            .order_by(RDBSignupTokenRedemption.redeemed_at.asc())
        )
        return [self._build_redemption(rdb) for rdb in result.scalars().all()]

    async def create_redemption(
        self,
        session: AsyncSession,
        create: SignupTokenRedemptionCreate,
    ) -> SignupTokenRedemption:
        """Create Signup token usage record.

        :param session: Database session
        :param create: Create data
        :return: Created usage record
        """
        rdb_redemption = RDBSignupTokenRedemption(
            signup_token_id=create.signup_token_id,
            user_id=create.user_id,
            email=create.email,
            ip_address=create.ip_address,
            user_agent=create.user_agent,
            redeemed_at=create.redeemed_at,
        )
        session.add(rdb_redemption)
        await session.flush()
        return self._build_redemption(rdb_redemption)

    async def _get_rdb_by_token_hash(
        self,
        session: AsyncSession,
        token_hash: str,
    ) -> RDBSignupToken | None:
        """Fetch RDBSignupToken by token hash."""
        result = await session.execute(
            sa.select(RDBSignupToken).where(RDBSignupToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    def _build(self, rdb: RDBSignupToken) -> SignupToken:
        """Convert RDBSignupToken to domain model."""
        return SignupToken(
            id=rdb.id,
            token_hash=rdb.token_hash,
            email=rdb.email,
            created_by_user_id=rdb.created_by_user_id,
            delivery_method=rdb.delivery_method,
            expires_at=rdb.expires_at,
            max_uses=rdb.max_uses,
            used_count=rdb.used_count,
            revoked_at=rdb.revoked_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    def _build_redemption(
        self,
        rdb: RDBSignupTokenRedemption,
    ) -> SignupTokenRedemption:
        """Convert RDBSignupTokenRedemption to domain model."""
        return SignupTokenRedemption(
            id=rdb.id,
            signup_token_id=rdb.signup_token_id,
            user_id=rdb.user_id,
            email=rdb.email,
            ip_address=rdb.ip_address,
            user_agent=rdb.user_agent,
            redeemed_at=rdb.redeemed_at,
        )
