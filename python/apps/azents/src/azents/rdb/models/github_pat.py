"""GitHub PAT model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBGitHubPAT(RDBModel):
    """GitHub PAT table.

    Stores PATs by workspace and user.
    All GitHub toolkits in the same workspace share one PAT.
    """

    __tablename__ = "github_pats"

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
    encrypted_token: Mapped[str] = mapped_column(sa.Text, nullable=False)
    github_username: Mapped[str | None] = mapped_column(
        sa.String(100), nullable=True, default=None
    )
    display_hint: Mapped[str | None] = mapped_column(
        sa.String(20), nullable=True, default=None
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True, default=None
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

    UQ_WORKSPACE_USER = sa.UniqueConstraint(
        "workspace_id", "user_id", name="uq_github_pats_workspace_user"
    )
    IX_WORKSPACE_ID = sa.Index("ix_github_pats_workspace_id", "workspace_id")

    __table_args__ = (UQ_WORKSPACE_USER, IX_WORKSPACE_ID)
