"""Password reset token model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBPasswordResetToken(RDBModel):
    """Password reset token table."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )
    used_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        default=None,
    )
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
        name="uq_password_reset_tokens_token_hash",
    )
    IX_USER_ID = sa.Index("ix_password_reset_tokens_user_id", "user_id")
    IX_CREATED_BY_USER_ID = sa.Index(
        "ix_password_reset_tokens_created_by_user_id",
        "created_by_user_id",
    )
    IX_EXPIRES_AT = sa.Index("ix_password_reset_tokens_expires_at", "expires_at")
    IX_REVOKED_AT = sa.Index("ix_password_reset_tokens_revoked_at", "revoked_at")

    __table_args__ = (
        UQ_TOKEN_HASH,
        IX_USER_ID,
        IX_CREATED_BY_USER_ID,
        IX_EXPIRES_AT,
        IX_REVOKED_AT,
    )


class RDBPasswordResetTokenRedemption(RDBModel):
    """Password reset token usage record table."""

    __tablename__ = "password_reset_token_redemptions"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    password_reset_token_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("password_reset_tokens.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    redeemed_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    ip_address: Mapped[str | None] = mapped_column(sa.String(64), default=None)
    user_agent: Mapped[str | None] = mapped_column(sa.Text, default=None)

    IX_PASSWORD_RESET_TOKEN_ID = sa.Index(
        "ix_password_reset_token_redemptions_password_reset_token_id",
        "password_reset_token_id",
    )
    IX_USER_ID = sa.Index("ix_password_reset_token_redemptions_user_id", "user_id")
    IX_REDEEMED_AT = sa.Index(
        "ix_password_reset_token_redemptions_redeemed_at",
        "redeemed_at",
    )

    __table_args__ = (
        IX_PASSWORD_RESET_TOKEN_ID,
        IX_USER_ID,
        IX_REDEEMED_AT,
    )
