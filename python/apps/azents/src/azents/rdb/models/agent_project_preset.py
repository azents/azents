"""Agent Project preset model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBAgentProjectPreset(RDBModel):
    """Agent-owned remembered Project path preset."""

    __tablename__ = "agent_project_presets"

    UQ_AGENT_PATH = sa.UniqueConstraint(
        "agent_id",
        "path",
        name="uq_agent_project_presets_agent_path",
    )
    IX_AGENT_UPDATED = sa.Index(
        "ix_agent_project_presets_agent_updated",
        "agent_id",
        "updated_at",
    )

    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
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

    __table_args__ = (UQ_AGENT_PATH, IX_AGENT_UPDATED)
