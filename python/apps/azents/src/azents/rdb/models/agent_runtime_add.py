"""Durable Agent Runtime addition receipt model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBAgentRuntimeAddReceipt(RDBModel):
    """Exact idempotency evidence for one committed Runtime addition."""

    __tablename__ = "agent_runtime_add_receipts"

    UQ_AGENT_IDEMPOTENCY_KEY = sa.Index(
        "uq_agent_runtime_add_receipts_agent_idempotency",
        "agent_id",
        "idempotency_key",
        unique=True,
    )
    IX_AGENT_CREATED_AT = sa.Index(
        "ix_agent_runtime_add_receipts_agent_created_at",
        "agent_id",
        "created_at",
    )
    CK_CAPABILITY_VERSIONS = sa.CheckConstraint(
        "expected_capability_version >= 1 "
        "AND committed_capability_version = expected_capability_version + 1",
        name="ck_agent_runtime_add_receipts_capability_versions",
    )
    CK_PROFILE_VERSION = sa.CheckConstraint(
        "committed_runtime_profile_selection_version >= 2",
        name="ck_agent_runtime_add_receipts_profile_version",
    )
    CK_RUNTIME_GENERATION = sa.CheckConstraint(
        "runtime_desired_generation >= 0",
        name="ck_agent_runtime_add_receipts_runtime_generation",
    )
    CK_CONFIGURATION_SEQUENCE = sa.CheckConstraint(
        "runtime_configuration_sequence >= 1",
        name="ck_agent_runtime_add_receipts_configuration_sequence",
    )

    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    workspace_runtime_profile_id: Mapped[str] = mapped_column(
        sa.String(32), nullable=False
    )
    expected_capability_version: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    committed_capability_version: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    committed_runtime_profile_selection_version: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    agent_runtime_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="CASCADE"),
        nullable=False,
    )
    runtime_configuration_sequence: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    runtime_configuration_digest: Mapped[str] = mapped_column(
        sa.String(64), nullable=False
    )
    runtime_desired_generation: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
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

    __table_args__ = (
        UQ_AGENT_IDEMPOTENCY_KEY,
        IX_AGENT_CREATED_AT,
        CK_CAPABILITY_VERSIONS,
        CK_PROFILE_VERSION,
        CK_RUNTIME_GENERATION,
        CK_CONFIGURATION_SEQUENCE,
    )
