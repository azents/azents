"""SignupTokenRepository tests."""

import datetime

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import SignupTokenDeliveryMethod
from azents.repos.signup_token import SignupTokenRepository
from azents.repos.signup_token.data import (
    SignupTokenCreate,
    SignupTokenRedemptionCreate,
    SignupTokenUnavailable,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate


class TestSignupTokenRepository:
    """SignupTokenRepository tests."""

    async def test_claim_for_redemption_increments_used_count(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Increment used_count when claiming redeem."""
        repo = SignupTokenRepository()
        now = datetime.datetime.now(datetime.UTC)
        await repo.create(
            rdb_session,
            SignupTokenCreate(
                token_hash="hash-a",
                email="user@example.com",
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=now + datetime.timedelta(hours=1),
                max_uses=1,
            ),
        )

        result = await repo.claim_for_redemption(
            rdb_session,
            "hash-a",
            now=now,
        )

        assert isinstance(result, Success)
        assert result.value.used_count == 1

    async def test_claim_for_redemption_rejects_exhausted_token(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Token with exhausted use count cannot be claimed."""
        repo = SignupTokenRepository()
        now = datetime.datetime.now(datetime.UTC)
        await repo.create(
            rdb_session,
            SignupTokenCreate(
                token_hash="hash-b",
                email="user@example.com",
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=now + datetime.timedelta(hours=1),
                max_uses=1,
            ),
        )
        assert isinstance(
            await repo.claim_for_redemption(rdb_session, "hash-b", now=now),
            Success,
        )

        result = await repo.claim_for_redemption(rdb_session, "hash-b", now=now)

        assert isinstance(result, Failure)
        assert isinstance(result.error, SignupTokenUnavailable)

    async def test_create_redemption(self, rdb_session: AsyncSession) -> None:
        """Create Signup token usage record."""
        repo = SignupTokenRepository()
        now = datetime.datetime.now(datetime.UTC)
        token = await repo.create(
            rdb_session,
            SignupTokenCreate(
                token_hash="hash-c",
                email="user@example.com",
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=now + datetime.timedelta(hours=1),
                max_uses=1,
            ),
        )

        user = await UserRepository().create(
            rdb_session,
            UserCreate(email="redemption-user@example.com"),
        )
        redemption = await repo.create_redemption(
            rdb_session,
            SignupTokenRedemptionCreate(
                signup_token_id=token.id,
                user_id=user.id,
                email="user@example.com",
                ip_address="127.0.0.1",
                user_agent="pytest",
                redeemed_at=now,
            ),
        )

        assert redemption.signup_token_id == token.id
        assert redemption.email == "user@example.com"
