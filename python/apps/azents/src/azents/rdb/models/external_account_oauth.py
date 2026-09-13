"""Provider identity OAuth attempt persistence models."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    ExternalAccountOAuthAttemptStatus,
    ExternalChannelProvider,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.models.external_channel import external_channel_provider_enum
from azents.rdb.types.datetime import TimeZoneDateTime

external_account_oauth_attempt_status_enum = ENUM(
    ExternalAccountOAuthAttemptStatus,
    name="external_account_oauth_attempt_status",
    create_type=False,
    values_callable=lambda values: [value.value for value in values],
)


class RDBExternalAccountOAuthAttempt(RDBModel):
    """Short-lived, single-use provider identity OAuth attempt."""

    __tablename__ = "external_account_oauth_attempts"

    UQ_STATE_HASH = sa.UniqueConstraint(
        "state_hash",
        name="uq_external_account_oauth_attempts_state_hash",
    )
    IX_USER_SESSION = sa.Index(
        "ix_external_account_oauth_attempts_user_session",
        "user_id",
        "auth_session_id",
    )
    IX_EXPIRES_AT = sa.Index(
        "ix_external_account_oauth_attempts_expires_at",
        "expires_at",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    state_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    auth_session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[ExternalChannelProvider] = mapped_column(
        external_channel_provider_enum,
        nullable=False,
    )
    setting_generation: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
    )
    redirect_uri: Mapped[str] = mapped_column(sa.Text, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    encrypted_pkce_verifier: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    status: Mapped[ExternalAccountOAuthAttemptStatus] = mapped_column(
        external_account_oauth_attempt_status_enum,
        nullable=False,
        default=ExternalAccountOAuthAttemptStatus.OPEN,
        server_default=ExternalAccountOAuthAttemptStatus.OPEN.value,
    )
    claimed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    failed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    failure_code: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (UQ_STATE_HASH, IX_USER_SESSION, IX_EXPIRES_AT)
