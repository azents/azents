"""Current Memory results and server work associations over common Sessions."""

import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationWorkKind,
)
from azents.core.json_value import JSONValue
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime

scope_enum = ENUM(ConsolidationScope, name="consolidation_scope", create_type=False)
work_kind_enum = ENUM(
    ConsolidationWorkKind, name="consolidation_work_kind", create_type=False
)


class RDBMemoryUnit(RDBModel):
    """One current result and routing association, without an independent owner."""

    __tablename__ = "memory_units"
    CK_SCOPE = sa.CheckConstraint(
        "(scope = 'TEAM' AND associated_user_id IS NULL) OR (scope = 'USER' AND "
        "associated_user_id IS NOT NULL)",
        name="ck_memory_units_scope",
    )
    UQ_SCOPE = sa.UniqueConstraint(
        "workspace_id",
        "agent_id",
        "scope",
        "associated_user_id",
        name="uq_memory_units_scope",
        postgresql_nulls_not_distinct=True,
    )
    CK_RESULT = sa.CheckConstraint(
        "(accepted_at IS NULL AND markdown IS NULL AND rendered_block IS NULL) OR "
        "(accepted_at IS NOT NULL AND markdown IS NOT NULL AND rendered_block IS NOT "
        "NULL AND octet_length(rendered_block) <= 10000)",
        name="ck_memory_units_current_result",
    )
    IX_RETRY = sa.Index("ix_memory_units_retry_at", "retry_at")
    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("agents.id", ondelete="CASCADE")
    )
    scope: Mapped[ConsolidationScope] = mapped_column(scope_enum)
    associated_user_id: Mapped[str | None] = mapped_column(
        sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    active_session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    markdown: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    rendered_block: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    accepted_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True
    )
    retry_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True
    )
    failure_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default="0", init=False
    )
    __table_args__ = (CK_SCOPE, UQ_SCOPE, CK_RESULT, IX_RETRY)


class RDBMemoryExecution(RDBModel):
    """Detached common Session binding and its safe original accepted outcome."""

    __tablename__ = "memory_executions"
    IX_UNIT = sa.Index("ix_memory_executions_unit_id", "unit_id")
    CK_TURNS = sa.CheckConstraint(
        "started_turns >= 0", name="ck_memory_executions_turns"
    )
    CK_ACCEPTED = sa.CheckConstraint(
        "(accepted_at IS NULL AND accepted_tool_call_id IS NULL AND rendered_bytes IS "
        "NULL AND settled_work_count IS NULL) OR (accepted_at IS NOT NULL AND "
        "accepted_tool_call_id IS NOT NULL AND rendered_bytes IS NOT NULL AND "
        "settled_work_count IS NOT NULL AND rendered_bytes BETWEEN 0 AND 10000 AND "
        "settled_work_count >= 0)",
        name="ck_memory_executions_accepted",
    )
    session_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    unit_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("memory_units.id", ondelete="CASCADE")
    )
    deadline_at: Mapped[datetime.datetime] = mapped_column(TimeZoneDateTime)
    execution_policy: Mapped[dict[str, JSONValue]] = mapped_column(JSONB)
    started_turns: Mapped[int] = mapped_column(sa.Integer)
    accepted_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True
    )
    accepted_tool_call_id: Mapped[str | None] = mapped_column(
        sa.String(256), nullable=True
    )
    rendered_bytes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    settled_work_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    __table_args__ = (IX_UNIT, CK_TURNS, CK_ACCEPTED)


class RDBMemoryWork(RDBModel):
    """Pending scheduling changes; only exact server associations are settled."""

    __tablename__ = "memory_work"
    IX_UNIT = sa.Index("ix_memory_work_unit_pending", "unit_id", "created_at", "id")
    IX_ADMITTED = sa.Index(
        "ix_memory_work_admitted_session_id",
        "admitted_session_id",
        postgresql_where=sa.text("admitted_session_id IS NOT NULL"),
    )
    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    unit_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("memory_units.id", ondelete="CASCADE")
    )
    source_session_id: Mapped[str] = mapped_column(sa.String(32))
    kind: Mapped[ConsolidationWorkKind] = mapped_column(work_kind_enum)
    admitted_session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("memory_executions.session_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    __table_args__ = (IX_UNIT, IX_ADMITTED)
