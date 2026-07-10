"""AgentRun to input event association model."""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel


class RDBAgentRunInputEvent(RDBModel):
    """Ordered input event consumed by an AgentRun."""

    __tablename__ = "agent_run_input_events"

    CK_INPUT_ORDER = sa.CheckConstraint(
        "input_order >= 0",
        name="ck_agent_run_input_events_input_order",
    )
    UQ_RUN_INPUT_ORDER = sa.UniqueConstraint(
        "agent_run_id",
        "input_order",
        name="uq_agent_run_input_events_run_input_order",
    )
    IX_EVENT_RUN = sa.Index(
        "ix_agent_run_input_events_event_run",
        "event_id",
        "agent_run_id",
    )
    IX_RUN_INPUT_ORDER = sa.Index(
        "ix_agent_run_input_events_run_input_order",
        "agent_run_id",
        "input_order",
    )

    agent_run_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    input_order: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    __table_args__ = (
        CK_INPUT_ORDER,
        UQ_RUN_INPUT_ORDER,
        IX_EVENT_RUN,
        IX_RUN_INPUT_ORDER,
    )
