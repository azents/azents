"""ModelFile active run pin model."""

import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBModelFilePin(RDBModel):
    """ModelFile pin held by an active AgentRun."""

    __tablename__ = "model_file_pins"

    IX_MODEL_FILE_ID = sa.Index("ix_model_file_pins_model_file_id", "model_file_id")
    IX_RUN_ID = sa.Index("ix_model_file_pins_run_id", "run_id")
    UQ_MODEL_FILE_RUN = sa.UniqueConstraint(
        "model_file_id",
        "run_id",
        name="uq_model_file_pins_model_file_run",
    )

    model_file_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("model_files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (IX_MODEL_FILE_ID, IX_RUN_ID, UQ_MODEL_FILE_RUN)
