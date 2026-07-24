"""Agent automatic Project policy item model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBAgentAutomaticProjectItem(RDBModel):
    """One ordered normalized Project path in an Agent automatic policy."""

    __tablename__ = "agent_automatic_project_items"

    UQ_AGENT_PATH = sa.UniqueConstraint(
        "agent_id",
        "path",
        name="uq_agent_automatic_project_items_agent_path",
    )
    UQ_AGENT_POSITION = sa.UniqueConstraint(
        "agent_id",
        "position",
        name="uq_agent_automatic_project_items_agent_position",
    )
    IX_AGENT_POSITION = sa.Index(
        "ix_agent_automatic_project_items_agent_position",
        "agent_id",
        "position",
    )

    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "agent_automatic_project_settings.agent_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False)

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

    __table_args__ = (UQ_AGENT_PATH, UQ_AGENT_POSITION, IX_AGENT_POSITION)
