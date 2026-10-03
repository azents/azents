"""Private consolidation ownership, work, drafts and purge-safe dependencies."""

import datetime

import sqlalchemy as sa
from azcommon.types import JSONValue
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

import azents.rdb.models.agent as _agent  # noqa: F401  # Register owner FK metadata.
import azents.rdb.models.user as _user  # noqa: F401  # Register owner FK metadata.
import azents.rdb.models.workspace as _workspace  # noqa: F401  # Register owner FK metadata.
from azents.core.historical_memory_consolidation import (
    ConsolidationAttemptState,
    ConsolidationScope,
    ConsolidationWorkKind,
    ConsolidationWorkState,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBConsolidationUnit(RDBModel):
    """One exact-scope owner with a single fenced current attempt and result."""

    __tablename__ = "historical_consolidation_units"
    CK_SCOPE_OWNER = sa.CheckConstraint(
        "(scope = 'TEAM' AND associated_user_id IS NULL) OR "
        "(scope = 'USER' AND associated_user_id IS NOT NULL)",
        name="ck_historical_consolidation_units_scope_owner",
    )
    CK_OWNER = sa.CheckConstraint(
        "owner_generation >= 0 AND "
        "((owner_token IS NULL AND lease_until IS NULL AND active_attempt_id IS NULL) "
        "OR (owner_token IS NOT NULL AND lease_until IS NOT NULL "
        "AND active_attempt_id IS NOT NULL))",
        name="ck_historical_consolidation_units_owner",
    )
    IX_TEAM = sa.Index(
        "uq_historical_consolidation_units_team",
        "workspace_id",
        "agent_id",
        unique=True,
        postgresql_where=sa.text("associated_user_id IS NULL"),
    )
    IX_USER = sa.Index(
        "uq_historical_consolidation_units_user",
        "workspace_id",
        "agent_id",
        "associated_user_id",
        unique=True,
        postgresql_where=sa.text("associated_user_id IS NOT NULL"),
    )
    IX_RETRY = sa.Index("ix_historical_consolidation_units_retry_at", "retry_at")

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[ConsolidationScope] = mapped_column(
        ENUM(ConsolidationScope, name="consolidation_scope", create_type=False),
        nullable=False,
    )
    associated_user_id: Mapped[str | None] = mapped_column(
        sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    owner_generation: Mapped[int] = mapped_column(
        sa.BigInteger, init=False, nullable=False, server_default="0"
    )
    owner_token: Mapped[str | None] = mapped_column(
        sa.String(32), init=False, nullable=True, default=None
    )
    lease_until: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
    active_attempt_id: Mapped[str | None] = mapped_column(
        sa.String(32), init=False, nullable=True, default=None
    )
    published_revision_id: Mapped[str | None] = mapped_column(
        sa.String(32), init=False, nullable=True, default=None
    )
    retry_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
    failure_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    no_progress_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    __table_args__ = (CK_SCOPE_OWNER, CK_OWNER, IX_TEAM, IX_USER, IX_RETRY)


class RDBConsolidationWork(RDBModel):
    """Lock-independent metadata enrollment with exact, not watermark, outcomes."""

    __tablename__ = "historical_consolidation_work"
    CK_SCOPE_OWNER = sa.CheckConstraint(
        "(scope = 'TEAM' AND associated_user_id IS NULL) OR "
        "(scope = 'USER' AND associated_user_id IS NOT NULL)",
        name="ck_historical_consolidation_work_scope_owner",
    )
    CK_GENERATIONS = sa.CheckConstraint(
        "summary_generation >= 0 AND availability_generation >= 1",
        name="ck_historical_consolidation_work_generations",
    )
    UQ_VERSION = sa.UniqueConstraint(
        "agent_id",
        "workspace_id",
        "scope",
        "associated_user_id",
        "source_session_id",
        "summary_generation",
        "availability_generation",
        "membership_grant_id",
        "kind",
        name="uq_historical_consolidation_work_version",
        postgresql_nulls_not_distinct=True,
    )
    UQ_SEQUENCE = sa.UniqueConstraint(
        "sequence", name="uq_historical_consolidation_work_sequence"
    )
    IX_PENDING = sa.Index(
        "ix_historical_consolidation_work_pending",
        "workspace_id",
        "agent_id",
        "scope",
        "associated_user_id",
        "sequence",
        postgresql_where=sa.text("state IN ('PENDING', 'CONSIDERED')"),
    )

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[ConsolidationScope] = mapped_column(
        ENUM(ConsolidationScope, name="consolidation_scope", create_type=False),
        nullable=False,
    )
    associated_user_id: Mapped[str | None] = mapped_column(
        sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    source_session_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    summary_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    availability_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    evidence_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    membership_grant_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    kind: Mapped[ConsolidationWorkKind] = mapped_column(
        ENUM(ConsolidationWorkKind, name="consolidation_work_kind", create_type=False),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(
        sa.BigInteger, sa.Identity(), init=False, nullable=False
    )
    state: Mapped[ConsolidationWorkState] = mapped_column(
        ENUM(
            ConsolidationWorkState, name="consolidation_work_state", create_type=False
        ),
        init=False,
        nullable=False,
        server_default="PENDING",
    )
    considered_draft_id: Mapped[str | None] = mapped_column(
        sa.String(32), init=False, nullable=True, default=None
    )
    published_revision_id: Mapped[str | None] = mapped_column(
        sa.String(32), init=False, nullable=True, default=None
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    __table_args__ = (
        CK_SCOPE_OWNER,
        CK_GENERATIONS,
        UQ_VERSION,
        UQ_SEQUENCE,
        IX_PENDING,
    )


class RDBConsolidationAttempt(RDBModel):
    """Internal lifecycle and bounded counters without a persisted conversation."""

    __tablename__ = "historical_consolidation_attempts"
    CK_COUNTERS = sa.CheckConstraint(
        "owner_generation >= 1 AND model_requests >= 0 AND tool_calls >= 0 "
        "AND input_tokens >= 0 AND output_tokens >= 0",
        name="ck_historical_consolidation_attempts_counters",
    )
    IX_UNIT = sa.Index("ix_historical_consolidation_attempts_unit_id", "unit_id")

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    unit_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("historical_consolidation_units.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    owner_token: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    deadline_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, nullable=False
    )
    pass_upper_sequence: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    membership_grant_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    observation_epoch: Mapped[int] = mapped_column(
        sa.BigInteger, init=False, nullable=False, server_default="0"
    )
    state: Mapped[ConsolidationAttemptState] = mapped_column(
        ENUM(
            ConsolidationAttemptState,
            name="consolidation_attempt_state",
            create_type=False,
        ),
        init=False,
        nullable=False,
        server_default="RUNNING",
    )
    model_requests: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    tool_calls: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    input_tokens: Mapped[int] = mapped_column(
        sa.BigInteger, init=False, nullable=False, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        sa.BigInteger, init=False, nullable=False, server_default="0"
    )
    model_operation_state: Mapped[dict[str, JSONValue] | None] = mapped_column(
        JSONB, init=False, nullable=True, default=None
    )
    failure_code: Mapped[str | None] = mapped_column(
        sa.String(120), init=False, nullable=True, default=None
    )
    completed_revision_id: Mapped[str | None] = mapped_column(
        sa.String(32), init=False, nullable=True, default=None
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    __table_args__ = (CK_COUNTERS, IX_UNIT)


class RDBConsolidationDraft(RDBModel):
    """One current private recoverable document set per independent unit."""

    __tablename__ = "historical_consolidation_drafts"
    UQ_UNIT = sa.UniqueConstraint(
        "unit_id", name="uq_historical_consolidation_drafts_unit"
    )
    CK_LIMITS = sa.CheckConstraint(
        "file_count >= 0 AND file_count <= 16 "
        "AND byte_count >= 0 AND byte_count <= 262144",
        name="ck_historical_consolidation_drafts_limits",
    )
    IX_PROGRESS = sa.Index(
        "ix_historical_consolidation_drafts_last_progress_at", "last_progress_at"
    )

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    unit_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("historical_consolidation_units.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    base_revision_id: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    file_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    byte_count: Mapped[int] = mapped_column(
        sa.BigInteger, init=False, nullable=False, server_default="0"
    )
    invalidated: Mapped[bool] = mapped_column(
        sa.Boolean, init=False, nullable=False, server_default=sa.false()
    )
    last_progress_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    __table_args__ = (UQ_UNIT, CK_LIMITS, IX_PROGRESS)


class RDBConsolidationDraftFile(RDBModel):
    """Current UTF-8 bytes only, with non-reused revisions on replacement."""

    __tablename__ = "historical_consolidation_draft_files"
    CK_SIZE = sa.CheckConstraint(
        "octet_length(content) <= 262144",
        name="ck_historical_consolidation_draft_files_size",
    )
    draft_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("historical_consolidation_drafts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    path: Mapped[str] = mapped_column(sa.String(512), primary_key=True)
    revision_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    __table_args__ = (CK_SIZE,)


class RDBConsolidationEvidence(RDBModel):
    """Body-free receipts for every source exposure within an active attempt."""

    __tablename__ = "historical_consolidation_evidence"
    UQ_VERSION = sa.UniqueConstraint(
        "attempt_id",
        "source_session_id",
        "summary_generation",
        "availability_generation",
        "membership_grant_id",
        name="uq_historical_consolidation_evidence_version",
        postgresql_nulls_not_distinct=True,
    )
    CK_VERSION = sa.CheckConstraint(
        "summary_generation >= 1 AND availability_generation >= 1 "
        "AND evidence_hash ~ '^[0-9a-f]{64}$'",
        name="ck_historical_consolidation_evidence_version",
    )
    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("historical_consolidation_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_session_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    summary_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    availability_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    membership_grant_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    __table_args__ = (UQ_VERSION, CK_VERSION)


class RDBConsolidationDraftDependency(RDBModel):
    """Complete draft influence independent of source-row deletion and receipts."""

    __tablename__ = "historical_consolidation_draft_dependencies"
    UQ_VERSION = sa.UniqueConstraint(
        "draft_id",
        "source_session_id",
        "summary_generation",
        "availability_generation",
        "membership_grant_id",
        name="uq_historical_consolidation_draft_dependencies_version",
        postgresql_nulls_not_distinct=True,
    )
    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("historical_consolidation_drafts.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_session_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    summary_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    availability_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    membership_grant_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    __table_args__ = (UQ_VERSION,)


class RDBConsolidationMutationReceipt(RDBModel):
    """Idempotent safe result metadata; no old bodies or raw request transcript."""

    __tablename__ = "historical_consolidation_mutation_receipts"
    CK_DIGEST = sa.CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'",
        name="ck_historical_consolidation_mutation_receipts_digest",
    )
    attempt_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("historical_consolidation_attempts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tool_call_id: Mapped[str] = mapped_column(sa.String(256), primary_key=True)
    request_digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    result_json: Mapped[dict[str, JSONValue]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    __table_args__ = (CK_DIGEST,)


class RDBConsolidationRevision(RDBModel):
    """Published immutable compact result retained while authorized snapshots refer."""

    __tablename__ = "historical_consolidation_revisions"
    CK_SIZE = sa.CheckConstraint(
        "octet_length(rendered_block) <= 10000",
        name="ck_historical_consolidation_revisions_size",
    )
    IX_UNIT = sa.Index("ix_historical_consolidation_revisions_unit_id", "unit_id")
    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    unit_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("historical_consolidation_units.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    markdown: Mapped[str] = mapped_column(sa.Text, nullable=False)
    rendered_block: Mapped[str] = mapped_column(sa.Text, nullable=False)
    published_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    __table_args__ = (CK_SIZE, IX_UNIT)


class RDBConsolidationRevisionDependency(RDBModel):
    """Purge-safe manifest identity, never cascading from a source Session."""

    __tablename__ = "historical_consolidation_revision_dependencies"
    UQ_VERSION = sa.UniqueConstraint(
        "revision_id",
        "source_session_id",
        "summary_generation",
        "availability_generation",
        "membership_grant_id",
        name="uq_historical_consolidation_revision_dependencies_version",
        postgresql_nulls_not_distinct=True,
    )
    IX_SOURCE = sa.Index(
        "ix_historical_consolidation_revision_dependencies_source", "source_session_id"
    )
    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("historical_consolidation_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_session_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    summary_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    availability_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    membership_grant_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    __table_args__ = (UQ_VERSION, IX_SOURCE)
