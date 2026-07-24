"""Agent automatic Project policy settings model."""

import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBAgentAutomaticProjectSetting(RDBModel):
    """Revisioned Agent policy for Projects added to automatic root Sessions."""

    __tablename__ = "agent_automatic_project_settings"

    CK_REVISION_POSITIVE = sa.CheckConstraint(
        "revision >= 1",
        name="ck_agent_automatic_project_settings_revision_positive",
    )

    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    revision: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=1,
        server_default=sa.text("1"),
    )
    updated_by_workspace_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspace_users.id", ondelete="SET NULL"),
        nullable=True,
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

    __table_args__ = (CK_REVISION_POSITIVE,)
