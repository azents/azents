"""Signup token model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import SignupTokenDeliveryMethod
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _signup_token_delivery_method_values(
    method_enum: type[SignupTokenDeliveryMethod],
) -> list[str]:
    """Return SignupTokenDeliveryMethod enum values stored in the DB."""
    return [method.value for method in method_enum]


signup_token_delivery_method_enum = ENUM(
    SignupTokenDeliveryMethod,
    name="signup_token_delivery_method",
    create_type=False,
    values_callable=_signup_token_delivery_method_values,
)


class RDBSignupToken(RDBModel):
    """Signup token table."""

    __tablename__ = "signup_tokens"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    email: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    delivery_method: Mapped[SignupTokenDeliveryMethod] = mapped_column(
        signup_token_delivery_method_enum,
        nullable=False,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    max_uses: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )
    used_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        default=None,
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    UQ_TOKEN_HASH = sa.UniqueConstraint(
        "token_hash",
        name="uq_signup_tokens_token_hash",
    )
    CK_MAX_USES_POSITIVE = sa.CheckConstraint(
        "max_uses > 0",
        name="ck_signup_tokens_max_uses_positive",
    )
    CK_USED_COUNT_RANGE = sa.CheckConstraint(
        "used_count >= 0 AND used_count <= max_uses",
        name="ck_signup_tokens_used_count_range",
    )
    IX_EMAIL = sa.Index("ix_signup_tokens_email", "email")
    IX_EXPIRES_AT = sa.Index("ix_signup_tokens_expires_at", "expires_at")
    IX_CREATED_BY_USER_ID = sa.Index(
        "ix_signup_tokens_created_by_user_id",
        "created_by_user_id",
    )
    IX_REVOKED_AT = sa.Index("ix_signup_tokens_revoked_at", "revoked_at")

    __table_args__ = (
        UQ_TOKEN_HASH,
        CK_MAX_USES_POSITIVE,
        CK_USED_COUNT_RANGE,
        IX_EMAIL,
        IX_EXPIRES_AT,
        IX_CREATED_BY_USER_ID,
        IX_REVOKED_AT,
    )


class RDBSignupTokenRedemption(RDBModel):
    """Signup token usage record table."""

    __tablename__ = "signup_token_redemptions"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    signup_token_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("signup_tokens.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    redeemed_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    ip_address: Mapped[str | None] = mapped_column(sa.String(64), default=None)
    user_agent: Mapped[str | None] = mapped_column(sa.Text, default=None)

    IX_SIGNUP_TOKEN_ID = sa.Index(
        "ix_signup_token_redemptions_signup_token_id",
        "signup_token_id",
    )
    IX_USER_ID = sa.Index("ix_signup_token_redemptions_user_id", "user_id")
    IX_EMAIL = sa.Index("ix_signup_token_redemptions_email", "email")
    IX_REDEEMED_AT = sa.Index(
        "ix_signup_token_redemptions_redeemed_at",
        "redeemed_at",
    )

    __table_args__ = (
        IX_SIGNUP_TOKEN_ID,
        IX_USER_ID,
        IX_EMAIL,
        IX_REDEEMED_AT,
    )
