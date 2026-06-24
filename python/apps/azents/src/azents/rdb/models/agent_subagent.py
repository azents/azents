"""AgentSubagent model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBAgentSubagent(RDBModel):
    """AgentSubagent junction table.

    Parent agent(role=AGENT)t child agent(role=SUBAGENT)t connectiont managet.
    """

    __tablename__ = "agent_subagents"

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
    subagent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)

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

    # Constraint condition and index.
    UQ_AGENT_SUBAGENT = sa.UniqueConstraint(
        "agent_id", "subagent_id", name="uq_agent_subagents_agent_subagent"
    )
    CK_NO_SELF_REF = sa.CheckConstraint(
        "agent_id != subagent_id", name="ck_agent_subagents_no_self_ref"
    )
    IX_AGENT_ID = sa.Index("ix_agent_subagents_agent_id", "agent_id")
    IX_SUBAGENT_ID = sa.Index("ix_agent_subagents_subagent_id", "subagent_id")

    __table_args__ = (
        UQ_AGENT_SUBAGENT,
        CK_NO_SELF_REF,
        IX_AGENT_ID,
        IX_SUBAGENT_ID,
    )
