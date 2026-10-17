"""Google-only unpublished attempts and one current Toolkit-owned grant."""

import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from azents.core.google_oauth import GoogleAttemptStatus, GoogleConnectionStatus
from azents.core.toolkit_ownership import ToolkitOwnerKind
from azents.rdb.models.base import RDBModel
from azents.rdb.models.toolkit import toolkit_owner_kind_enum
from azents.rdb.types.datetime import TimeZoneDateTime

google_attempt_status = ENUM(
    GoogleAttemptStatus,
    name="google_oauth_attempt_status",
    values_callable=lambda kind: [item.value for item in kind],
    create_type=False,
)
google_connection_status = ENUM(
    GoogleConnectionStatus,
    name="google_oauth_connection_status",
    values_callable=lambda kind: [item.value for item in kind],
    create_type=False,
)


class RDBGoogleConnection(RDBModel):
    """A replacement changes identity; routine token renewal retains it."""

    __tablename__ = "google_oauth_connections"

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    toolkit_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("toolkit_configs.id", ondelete="CASCADE")
    )
    client_id: Mapped[str] = mapped_column(sa.Text)
    encrypted_payload: Mapped[str] = mapped_column(sa.Text, repr=False)
    status: Mapped[GoogleConnectionStatus] = mapped_column(google_connection_status)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )
    UQ_TOOLKIT = sa.UniqueConstraint(
        "toolkit_id", name="uq_google_oauth_connections_toolkit"
    )
    IX_TOOLKIT = sa.Index("ix_google_oauth_connections_toolkit", "toolkit_id")
    __table_args__ = (UQ_TOOLKIT, IX_TOOLKIT)


class RDBGoogleAttempt(RDBModel):
    """Exact manager context with encrypted credentials until explicit publication."""

    __tablename__ = "google_oauth_attempts"

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    user_id: Mapped[str] = mapped_column(sa.String(32))
    session_id: Mapped[str] = mapped_column(sa.String(32))
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_kind: Mapped[ToolkitOwnerKind] = mapped_column(
        toolkit_owner_kind_enum, nullable=False
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "users.id", ondelete="CASCADE", name="fk_google_attempts_owner_user"
        ),
        nullable=True,
    )
    agent_id: Mapped[str | None] = mapped_column(
        sa.String(32), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    target_toolkit_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("toolkit_configs.id", ondelete="CASCADE"),
        nullable=True,
    )
    encrypted_setup: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, repr=False
    )
    encrypted_candidate: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, repr=False
    )
    status: Mapped[GoogleAttemptStatus] = mapped_column(google_attempt_status)
    expires_at: Mapped[datetime.datetime] = mapped_column(TimeZoneDateTime)
    published_toolkit_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    published_connection_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    final_settings: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    IX_SCOPE = sa.Index(
        "ix_google_oauth_attempts_scope", "session_id", "workspace_id", "agent_id"
    )
    IX_EXPIRY = sa.Index("ix_google_oauth_attempts_expiry", "expires_at")
    IX_TARGET = sa.Index("ix_google_oauth_attempts_target", "target_toolkit_id")
    IX_OWNER_USER = sa.Index("ix_google_oauth_attempts_owner_user", "owner_user_id")
    CK_OWNER = sa.CheckConstraint(
        "(owner_kind = 'workspace' AND workspace_id IS NOT NULL "
        "AND agent_id IS NULL AND owner_user_id IS NULL) OR "
        "(owner_kind = 'agent' AND workspace_id IS NOT NULL "
        "AND agent_id IS NOT NULL AND owner_user_id IS NULL) OR "
        "(owner_kind = 'user' AND workspace_id IS NOT NULL AND agent_id IS NULL "
        "AND owner_user_id IS NOT NULL AND owner_user_id = user_id)",
        name="ck_google_oauth_attempts_owner_shape",
    )
    __table_args__ = (IX_SCOPE, IX_EXPIRY, IX_TARGET, IX_OWNER_USER, CK_OWNER)
