"""Toolkit-owned GitHub user connections and staged one-use setup."""

import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from azents.core.github_user_oauth import (
    GitHubUserAttemptStatus,
    GitHubUserConnectionStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime

attempt_status_enum = ENUM(
    GitHubUserAttemptStatus,
    name="github_user_attempt_status",
    values_callable=lambda enum_type: [value.value for value in enum_type],
)
connection_status_enum = ENUM(
    GitHubUserConnectionStatus,
    name="github_user_connection_status",
    values_callable=lambda enum_type: [value.value for value in enum_type],
)


class RDBGitHubUserConnection(RDBModel):
    """Only the current credential is eligible for execution."""

    __tablename__ = "github_user_oauth_connections"
    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    toolkit_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("toolkit_configs.id", ondelete="CASCADE")
    )
    app_id: Mapped[str] = mapped_column(sa.String(64))
    account_id: Mapped[int] = mapped_column(sa.BigInteger)
    account_login: Mapped[str] = mapped_column(sa.String(255))
    account_avatar_url: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    encrypted_access_token: Mapped[str] = mapped_column(sa.Text, repr=False)
    encrypted_registration: Mapped[str] = mapped_column(sa.Text, repr=False)
    status: Mapped[GitHubUserConnectionStatus] = mapped_column(connection_status_enum)
    failure_reason: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
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
        "toolkit_id", name="uq_github_user_oauth_connections_toolkit"
    )
    IX_TOOLKIT = sa.Index("ix_github_user_oauth_connections_toolkit", "toolkit_id")
    __table_args__ = (UQ_TOOLKIT, IX_TOOLKIT)


class RDBGitHubUserAttempt(RDBModel):
    """Bound setup authority and encrypted candidate until confirmation."""

    __tablename__ = "github_user_oauth_attempts"
    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    toolkit_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("toolkit_configs.id", ondelete="CASCADE")
    )
    user_id: Mapped[str] = mapped_column(sa.String(32))
    session_id: Mapped[str] = mapped_column(sa.String(32))
    workspace_id: Mapped[str] = mapped_column(sa.String(32))
    agent_id: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    encrypted_setup: Mapped[str] = mapped_column(sa.Text, repr=False)
    encrypted_candidate: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, repr=False
    )
    captured_connection_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    status: Mapped[GitHubUserAttemptStatus] = mapped_column(attempt_status_enum)
    expires_at: Mapped[datetime.datetime] = mapped_column(TimeZoneDateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    IX_TOOLKIT = sa.Index("ix_github_user_oauth_attempts_toolkit", "toolkit_id")
    UQ_CURRENT = sa.Index(
        "uq_github_user_oauth_attempts_current",
        "toolkit_id",
        unique=True,
    )
    __table_args__ = (IX_TOOLKIT, UQ_CURRENT)


class RDBGitHubUserCreation(RDBModel):
    """Encrypted, short-lived new creation without a published Toolkit."""

    __tablename__ = "github_user_oauth_creations"
    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    user_id: Mapped[str] = mapped_column(sa.String(32))
    session_id: Mapped[str] = mapped_column(sa.String(32))
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    agent_id: Mapped[str | None] = mapped_column(
        sa.String(32), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    encrypted_setup: Mapped[str] = mapped_column(sa.Text, repr=False)
    encrypted_candidate: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, repr=False
    )
    status: Mapped[GitHubUserAttemptStatus] = mapped_column(attempt_status_enum)
    expires_at: Mapped[datetime.datetime] = mapped_column(TimeZoneDateTime)
    UQ_SUBJECT = sa.Index(
        "uq_github_user_oauth_creations_subject",
        "session_id",
        "workspace_id",
        "agent_id",
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    __table_args__ = (UQ_SUBJECT,)
