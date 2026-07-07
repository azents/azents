"""Session Workspace Project model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBSessionWorkspaceProject(RDBModel):
    """Project registered for an AgentSession working context."""

    __tablename__ = "session_workspace_projects"

    UQ_SESSION_PATH = sa.UniqueConstraint(
        "session_id",
        "path",
        name="uq_session_workspace_projects_session_path",
    )
    IX_SESSION_ID = sa.Index(
        "ix_session_workspace_projects_session_id",
        "session_id",
    )

    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(sa.Text, nullable=False)

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
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

    __table_args__ = (UQ_SESSION_PATH, IX_SESSION_ID)
