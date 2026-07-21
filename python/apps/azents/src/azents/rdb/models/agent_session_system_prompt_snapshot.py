"""Latest system prompt diagnostic snapshot for an AgentSession."""

import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.models.event import JSONValue
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBAgentSessionSystemPromptSnapshot(RDBModel):
    """Replaceable latest system prompt analysis for one AgentSession."""

    __tablename__ = "agent_session_system_prompt_snapshots"

    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    system_prompt: Mapped[dict[str, JSONValue]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )
