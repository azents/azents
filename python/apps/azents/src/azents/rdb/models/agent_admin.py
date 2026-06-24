"""AgentAdmin model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBAgentAdmin(RDBModel):
    """Agent admin table.

    Agentt WorkspaceUser betweent manage permissiont represents..
    """

    __tablename__ = "agent_admins"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspace_users.id", ondelete="CASCADE"),
        nullable=False,
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )

    # Constraint condition and index.
    UQ_AGENT_WORKSPACE_USER = sa.UniqueConstraint(
        "agent_id",
        "workspace_user_id",
        name="uq_agent_admins_agent_workspace_user",
    )
    IX_AGENT_ID = sa.Index("ix_agent_admins_agent_id", "agent_id")
    IX_WORKSPACE_USER_ID = sa.Index(
        "ix_agent_admins_workspace_user_id", "workspace_user_id"
    )

    __table_args__ = (UQ_AGENT_WORKSPACE_USER, IX_AGENT_ID, IX_WORKSPACE_USER_ID)
