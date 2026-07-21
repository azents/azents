"""SessionAgent tree model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import SessionAgentKind
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _session_agent_kind_values(enum_cls: type[SessionAgentKind]) -> list[str]:
    """Return SessionAgentKind enum values stored in the DB."""
    return [v.value for v in enum_cls]


session_agent_kind_enum = ENUM(
    SessionAgentKind,
    name="session_agent_kind",
    create_type=False,
    values_callable=_session_agent_kind_values,
)


class RDBSessionAgent(RDBModel):
    """Live participant tree node for a root session."""

    __tablename__ = "session_agents"

    UQ_AGENT_SESSION_ID = sa.UniqueConstraint(
        "agent_session_id",
        name="uq_session_agents_agent_session_id",
    )
    UQ_ROOT_PATH = sa.UniqueConstraint(
        "root_session_agent_id",
        "path",
        name="uq_session_agents_root_path",
    )
    UQ_PARENT_NAME = sa.UniqueConstraint(
        "parent_session_agent_id",
        "name",
        name="uq_session_agents_parent_name",
    )
    IX_CONTEXT_ID = sa.Index("ix_session_agents_context_id", "context_id")
    IX_ROOT_SESSION_AGENT_ID = sa.Index(
        "ix_session_agents_root_session_agent_id",
        "root_session_agent_id",
    )
    IX_PARENT_SESSION_AGENT_ID = sa.Index(
        "ix_session_agents_parent_session_agent_id",
        "parent_session_agent_id",
    )

    context_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_agent_contexts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    root_session_agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[SessionAgentKind] = mapped_column(
        session_agent_kind_enum,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    agent_type: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    parent_session_agent_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_agents.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    last_task_message: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    last_message_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    parent_observed_run_index: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    parent_observed_event_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )

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

    __table_args__ = (
        UQ_AGENT_SESSION_ID,
        UQ_ROOT_PATH,
        UQ_PARENT_NAME,
        IX_CONTEXT_ID,
        IX_ROOT_SESSION_AGENT_ID,
        IX_PARENT_SESSION_AGENT_ID,
    )
