"""Add private consolidation storage and version current prepared evidence."""

import datetime
import hashlib
import json
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "3be144f78dca"
down_revision: str | Sequence[str] | None = "459a4285993c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_prepared_evidence() -> None:
    """Version current bodies in bounded pages without retaining an old archive."""
    table = sa.table(
        "historical_memory_sources",
        sa.column("source_session_id", sa.String(32)),
        sa.column("completed_source_activity_at", sa.DateTime(timezone=True)),
        sa.column("completed_source_tail_event_id", sa.String(32)),
        sa.column("prepared_at", sa.DateTime(timezone=True)),
        sa.column("source_title_snapshot", sa.Text),
        sa.column("summary", sa.Text),
        sa.column("summary_generation", sa.BigInteger),
        sa.column("evidence_hash", sa.String(64)),
    )
    connection = op.get_bind()
    after: str | None = None
    while True:
        query = sa.select(table).where(
            table.c.prepared_at.is_not(None),
            table.c.summary_generation == 0,
        )
        if after is not None:
            query = query.where(table.c.source_session_id > after)
        rows = (
            connection.execute(query.order_by(table.c.source_session_id).limit(50))
            .mappings()
            .all()
        )
        if not rows:
            return
        for row in rows:
            activity = row["completed_source_activity_at"]
            prepared = row["prepared_at"]
            if not isinstance(activity, datetime.datetime) or not isinstance(
                prepared, datetime.datetime
            ):
                raise ValueError("Prepared Historical source has invalid timestamps.")
            payload = {
                "schema_version": 1,
                "summary": row["summary"] or None,
                "source_title": row["source_title_snapshot"],
                "source_activity_at": activity.astimezone(datetime.UTC).isoformat(),
                "source_tail_event_id": row["completed_source_tail_event_id"],
                "prepared_at": prepared.astimezone(datetime.UTC).isoformat(),
            }
            digest = hashlib.sha256(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            connection.execute(
                table.update()
                .where(
                    table.c.source_session_id == row["source_session_id"],
                    table.c.summary_generation == 0,
                )
                .values(summary_generation=1, evidence_hash=digest)
            )
        after = rows[-1]["source_session_id"]


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "workspace_users",
        sa.Column(
            "memory_grant_identity",
            sa.String(32),
            nullable=False,
            server_default=sa.text("replace(gen_random_uuid()::text, '-', '')"),
        ),
    )
    op.create_unique_constraint(
        "uq_workspace_users_memory_grant_identity",
        "workspace_users",
        ["memory_grant_identity"],
    )
    sa.Enum(
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "INVALIDATED",
        name="consolidation_attempt_state",
    ).create(op.get_bind())
    sa.Enum(
        "PENDING",
        "CONSIDERED",
        "PUBLISHED",
        "SUPERSEDED",
        name="consolidation_work_state",
    ).create(op.get_bind())
    sa.Enum("PREPARED", "REMOVED", "RESTORED", name="consolidation_work_kind").create(
        op.get_bind()
    )
    sa.Enum("TEAM", "USER", name="consolidation_scope").create(op.get_bind())
    op.create_table(
        "historical_consolidation_units",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column(
            "scope",
            postgresql.ENUM(
                "TEAM", "USER", name="consolidation_scope", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("associated_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "owner_generation", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column("owner_token", sa.String(length=32), nullable=True),
        sa.Column(
            "lease_until",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("active_attempt_id", sa.String(length=32), nullable=True),
        sa.Column("published_revision_id", sa.String(length=32), nullable=True),
        sa.Column(
            "retry_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "no_progress_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(scope = 'TEAM' AND associated_user_id IS NULL) OR "
            "(scope = 'USER' AND associated_user_id IS NOT NULL)",
            name="ck_historical_consolidation_units_scope_owner",
        ),
        sa.CheckConstraint(
            "owner_generation >= 0 AND "
            "((owner_token IS NULL AND lease_until IS NULL "
            "AND active_attempt_id IS NULL) "
            "OR (owner_token IS NOT NULL AND lease_until IS NOT NULL "
            "AND active_attempt_id IS NOT NULL))",
            name="ck_historical_consolidation_units_owner",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["associated_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_historical_consolidation_units_retry_at",
        "historical_consolidation_units",
        ["retry_at"],
        unique=False,
    )
    op.create_index(
        "uq_historical_consolidation_units_team",
        "historical_consolidation_units",
        ["workspace_id", "agent_id"],
        unique=True,
        postgresql_where=sa.text("associated_user_id IS NULL"),
    )
    op.create_index(
        "uq_historical_consolidation_units_user",
        "historical_consolidation_units",
        ["workspace_id", "agent_id", "associated_user_id"],
        unique=True,
        postgresql_where=sa.text("associated_user_id IS NOT NULL"),
    )
    op.create_table(
        "historical_consolidation_work",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column(
            "scope",
            postgresql.ENUM(
                "TEAM", "USER", name="consolidation_scope", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("associated_user_id", sa.String(length=32), nullable=True),
        sa.Column("source_session_id", sa.String(length=32), nullable=False),
        sa.Column("summary_generation", sa.BigInteger(), nullable=False),
        sa.Column("availability_generation", sa.BigInteger(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=True),
        sa.Column("membership_grant_id", sa.String(length=32), nullable=True),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "PREPARED",
                "REMOVED",
                "RESTORED",
                name="consolidation_work_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "sequence", sa.BigInteger(), sa.Identity(always=False), nullable=False
        ),
        sa.Column(
            "state",
            postgresql.ENUM(
                "PENDING",
                "CONSIDERED",
                "PUBLISHED",
                "SUPERSEDED",
                name="consolidation_work_state",
                create_type=False,
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("considered_draft_id", sa.String(length=32), nullable=True),
        sa.Column("published_revision_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(scope = 'TEAM' AND associated_user_id IS NULL) OR "
            "(scope = 'USER' AND associated_user_id IS NOT NULL)",
            name="ck_historical_consolidation_work_scope_owner",
        ),
        sa.CheckConstraint(
            "summary_generation >= 0 AND availability_generation >= 1",
            name="ck_historical_consolidation_work_generations",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["associated_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
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
        ),
        sa.UniqueConstraint(
            "sequence", name="uq_historical_consolidation_work_sequence"
        ),
    )
    op.create_index(
        "ix_historical_consolidation_work_pending",
        "historical_consolidation_work",
        ["workspace_id", "agent_id", "scope", "associated_user_id", "sequence"],
        unique=False,
        postgresql_where=sa.text("state IN ('PENDING', 'CONSIDERED')"),
    )
    op.create_table(
        "historical_consolidation_attempts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("unit_id", sa.String(length=32), nullable=False),
        sa.Column("owner_generation", sa.BigInteger(), nullable=False),
        sa.Column("owner_token", sa.String(length=32), nullable=False),
        sa.Column(
            "deadline_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("pass_upper_sequence", sa.BigInteger(), nullable=False),
        sa.Column("membership_grant_id", sa.String(length=32), nullable=True),
        sa.Column(
            "observation_epoch", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "state",
            postgresql.ENUM(
                "RUNNING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "INVALIDATED",
                name="consolidation_attempt_state",
                create_type=False,
            ),
            server_default="RUNNING",
            nullable=False,
        ),
        sa.Column("model_requests", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tool_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "model_operation_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("failure_code", sa.String(length=120), nullable=True),
        sa.Column("completed_revision_id", sa.String(length=32), nullable=True),
        sa.Column(
            "finished_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "owner_generation >= 1 AND model_requests >= 0 AND tool_calls >= 0 "
            "AND input_tokens >= 0 AND output_tokens >= 0",
            name="ck_historical_consolidation_attempts_counters",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"], ["historical_consolidation_units.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_historical_consolidation_attempts_unit_id",
        "historical_consolidation_attempts",
        ["unit_id"],
        unique=False,
    )
    op.create_table(
        "historical_consolidation_drafts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("unit_id", sa.String(length=32), nullable=False),
        sa.Column("revision_id", sa.String(length=32), nullable=False),
        sa.Column("base_revision_id", sa.String(length=32), nullable=True),
        sa.Column("file_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("byte_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "invalidated", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "last_progress_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "file_count >= 0 AND file_count <= 16 "
            "AND byte_count >= 0 AND byte_count <= 262144",
            name="ck_historical_consolidation_drafts_limits",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"], ["historical_consolidation_units.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("unit_id", name="uq_historical_consolidation_drafts_unit"),
    )
    op.create_index(
        "ix_historical_consolidation_drafts_last_progress_at",
        "historical_consolidation_drafts",
        ["last_progress_at"],
        unique=False,
    )
    op.create_table(
        "historical_consolidation_revisions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("unit_id", sa.String(length=32), nullable=False),
        sa.Column("attempt_id", sa.String(length=32), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("rendered_block", sa.Text(), nullable=False),
        sa.Column(
            "published_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(rendered_block) <= 10000",
            name="ck_historical_consolidation_revisions_size",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"], ["historical_consolidation_units.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_historical_consolidation_revisions_unit_id",
        "historical_consolidation_revisions",
        ["unit_id"],
        unique=False,
    )
    op.create_table(
        "historical_consolidation_draft_dependencies",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("draft_id", sa.String(length=32), nullable=False),
        sa.Column("source_session_id", sa.String(length=32), nullable=False),
        sa.Column("summary_generation", sa.BigInteger(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("availability_generation", sa.BigInteger(), nullable=False),
        sa.Column("membership_grant_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["historical_consolidation_drafts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "draft_id",
            "source_session_id",
            "summary_generation",
            "availability_generation",
            "membership_grant_id",
            name="uq_historical_consolidation_draft_dependencies_version",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "historical_consolidation_draft_files",
        sa.Column("draft_id", sa.String(length=32), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("revision_id", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "octet_length(content) <= 262144",
            name="ck_historical_consolidation_draft_files_size",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["historical_consolidation_drafts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("draft_id", "path"),
    )
    op.create_table(
        "historical_consolidation_evidence",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("attempt_id", sa.String(length=32), nullable=False),
        sa.Column("source_session_id", sa.String(length=32), nullable=False),
        sa.Column("summary_generation", sa.BigInteger(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("availability_generation", sa.BigInteger(), nullable=False),
        sa.Column("membership_grant_id", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "summary_generation >= 1 AND availability_generation >= 1 "
            "AND evidence_hash ~ '^[0-9a-f]{64}$'",
            name="ck_historical_consolidation_evidence_version",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["historical_consolidation_attempts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attempt_id",
            "source_session_id",
            "summary_generation",
            "availability_generation",
            "membership_grant_id",
            name="uq_historical_consolidation_evidence_version",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "historical_consolidation_mutation_receipts",
        sa.Column("attempt_id", sa.String(length=32), nullable=False),
        sa.Column("tool_call_id", sa.String(length=256), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'",
            name="ck_historical_consolidation_mutation_receipts_digest",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["historical_consolidation_attempts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("attempt_id", "tool_call_id"),
    )
    op.create_table(
        "historical_consolidation_revision_dependencies",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("revision_id", sa.String(length=32), nullable=False),
        sa.Column("source_session_id", sa.String(length=32), nullable=False),
        sa.Column("summary_generation", sa.BigInteger(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("availability_generation", sa.BigInteger(), nullable=False),
        sa.Column("membership_grant_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["historical_consolidation_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_id",
            "source_session_id",
            "summary_generation",
            "availability_generation",
            "membership_grant_id",
            name="uq_historical_consolidation_revision_dependencies_version",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_historical_consolidation_revision_dependencies_source",
        "historical_consolidation_revision_dependencies",
        ["source_session_id"],
        unique=False,
    )
    op.add_column(
        "historical_memory_sources",
        sa.Column(
            "summary_generation", sa.BigInteger(), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "historical_memory_sources",
        sa.Column("evidence_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "historical_memory_sources",
        sa.Column(
            "availability_generation",
            sa.BigInteger(),
            server_default="1",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_historical_memory_sources_evidence_generations",
        "historical_memory_sources",
        "summary_generation >= 0 AND availability_generation >= 1",
    )
    op.create_check_constraint(
        "ck_historical_memory_sources_evidence_hash",
        "historical_memory_sources",
        "evidence_hash IS NULL OR evidence_hash ~ '^[0-9a-f]{64}$'",
    )
    _backfill_prepared_evidence()
    _enroll_prepared_sources()


def _enroll_prepared_sources() -> None:
    """Seed exact authorized prepared versions in bounded, idempotent pages."""
    connection = op.get_bind()
    after = ""
    while True:
        rows = (
            connection.execute(
                sa.text(
                    """
                SELECT h.source_session_id
                FROM historical_memory_sources h
                JOIN agent_sessions s ON s.id = h.source_session_id
                JOIN agents a ON a.id = s.agent_id
                LEFT JOIN workspace_users m ON m.workspace_id = s.workspace_id
                    AND m.user_id = s.associated_user_id
                WHERE h.source_session_id > :after AND h.prepared_at IS NOT NULL
                    AND h.summary_generation > 0 AND h.evidence_hash IS NOT NULL
                    AND s.status = 'active' AND s.session_kind = 'root'
                    AND a.memory_enabled AND a.lifecycle_status = 'active'
                    AND (
                        (s.product_mode = 'team' AND s.associated_user_id IS NULL)
                        OR (s.product_mode = 'user'
                            AND m.memory_grant_identity IS NOT NULL)
                    )
                ORDER BY h.source_session_id LIMIT 50
                """
                ),
                {"after": after},
            )
            .scalars()
            .all()
        )
        if not rows:
            return
        connection.execute(
            sa.text(
                """
                INSERT INTO historical_consolidation_work
                    (id, agent_id, workspace_id, scope, associated_user_id,
                    source_session_id, summary_generation, availability_generation,
                    evidence_hash, membership_grant_id, kind)
                SELECT replace(gen_random_uuid()::text, '-', ''),
                    s.agent_id, s.workspace_id,
                    upper(s.product_mode::text)::consolidation_scope,
                    s.associated_user_id, h.source_session_id,
                    h.summary_generation, h.availability_generation, h.evidence_hash,
                    m.memory_grant_identity, 'PREPARED'::consolidation_work_kind
                FROM historical_memory_sources h
                JOIN agent_sessions s ON s.id = h.source_session_id
                LEFT JOIN workspace_users m ON m.workspace_id = s.workspace_id
                    AND m.user_id = s.associated_user_id
                WHERE h.source_session_id = ANY(:ids)
                ON CONFLICT ON CONSTRAINT uq_historical_consolidation_work_version
                    DO NOTHING
                """
            ),
            {"ids": rows},
        )
        after = rows[-1]


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_workspace_users_memory_grant_identity", "workspace_users", type_="unique"
    )
    op.drop_column("workspace_users", "memory_grant_identity")
    op.drop_constraint(
        "ck_historical_memory_sources_evidence_hash",
        "historical_memory_sources",
        type_="check",
    )
    op.drop_constraint(
        "ck_historical_memory_sources_evidence_generations",
        "historical_memory_sources",
        type_="check",
    )
    op.drop_column("historical_memory_sources", "availability_generation")
    op.drop_column("historical_memory_sources", "evidence_hash")
    op.drop_column("historical_memory_sources", "summary_generation")
    op.drop_index(
        "ix_historical_consolidation_revision_dependencies_source",
        table_name="historical_consolidation_revision_dependencies",
    )
    op.drop_table("historical_consolidation_revision_dependencies")
    op.drop_table("historical_consolidation_mutation_receipts")
    op.drop_table("historical_consolidation_evidence")
    op.drop_table("historical_consolidation_draft_files")
    op.drop_table("historical_consolidation_draft_dependencies")
    op.drop_index(
        "ix_historical_consolidation_revisions_unit_id",
        table_name="historical_consolidation_revisions",
    )
    op.drop_table("historical_consolidation_revisions")
    op.drop_index(
        "ix_historical_consolidation_drafts_last_progress_at",
        table_name="historical_consolidation_drafts",
    )
    op.drop_table("historical_consolidation_drafts")
    op.drop_index(
        "ix_historical_consolidation_attempts_unit_id",
        table_name="historical_consolidation_attempts",
    )
    op.drop_table("historical_consolidation_attempts")
    op.drop_index(
        "ix_historical_consolidation_work_pending",
        table_name="historical_consolidation_work",
        postgresql_where=sa.text("state IN ('PENDING', 'CONSIDERED')"),
    )
    op.drop_table("historical_consolidation_work")
    op.drop_index(
        "uq_historical_consolidation_units_user",
        table_name="historical_consolidation_units",
        postgresql_where=sa.text("associated_user_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_historical_consolidation_units_team",
        table_name="historical_consolidation_units",
        postgresql_where=sa.text("associated_user_id IS NULL"),
    )
    op.drop_index(
        "ix_historical_consolidation_units_retry_at",
        table_name="historical_consolidation_units",
    )
    op.drop_table("historical_consolidation_units")
    sa.Enum("TEAM", "USER", name="consolidation_scope").drop(op.get_bind())
    sa.Enum("PREPARED", "REMOVED", "RESTORED", name="consolidation_work_kind").drop(
        op.get_bind()
    )
    sa.Enum(
        "PENDING",
        "CONSIDERED",
        "PUBLISHED",
        "SUPERSEDED",
        name="consolidation_work_state",
    ).drop(op.get_bind())
    sa.Enum(
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "INVALIDATED",
        name="consolidation_attempt_state",
    ).drop(op.get_bind())
