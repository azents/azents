"""xAI OAuth session model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.xai_oauth import (
    XaiOAuthConnectionMethod,
    XaiOAuthSessionStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _connection_method_values(
    enum_cls: type[XaiOAuthConnectionMethod],
) -> list[str]:
    """Return xAI OAuth connection method values stored in the DB."""
    return [v.value for v in enum_cls]


def _session_status_values(enum_cls: type[XaiOAuthSessionStatus]) -> list[str]:
    """Return xAI OAuth session status values stored in the DB."""
    return [v.value for v in enum_cls]


xai_oauth_connection_method_enum = ENUM(
    XaiOAuthConnectionMethod,
    name="xai_oauth_connection_method",
    create_type=False,
    values_callable=_connection_method_values,
)
xai_oauth_session_status_enum = ENUM(
    XaiOAuthSessionStatus,
    name="xai_oauth_session_status",
    create_type=False,
    values_callable=_session_status_values,
)


class RDBXaiOAuthSession(RDBModel):
    """xAI OAuth device-code session table."""

    __tablename__ = "xai_oauth_sessions"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    method: Mapped[XaiOAuthConnectionMethod] = mapped_column(
        xai_oauth_connection_method_enum,
        nullable=False,
    )
    encrypted_device_code: Mapped[str] = mapped_column(sa.Text, nullable=False)
    user_code: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    verification_uri: Mapped[str] = mapped_column(sa.Text, nullable=False)
    interval_seconds: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    status: Mapped[XaiOAuthSessionStatus] = mapped_column(
        xai_oauth_session_status_enum,
        nullable=False,
        default=XaiOAuthSessionStatus.PENDING,
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

    IX_WORKSPACE_ID = sa.Index("ix_xai_oauth_sessions_workspace_id", "workspace_id")
    IX_USER_ID = sa.Index("ix_xai_oauth_sessions_user_id", "user_id")

    __table_args__ = (IX_WORKSPACE_ID, IX_USER_ID)
