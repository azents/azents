"""Replace consolidation authoring state with common Memory execution."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "95521a5a1bbc"
down_revision: str | Sequence[str] | None = "6a05f4a01f6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_units",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column(
            "scope",
            postgresql.ENUM(
                "TEAM", "USER", name="consolidation_scope", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("associated_user_id", sa.String(length=32), nullable=True),
        sa.Column("active_session_id", sa.String(length=32), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("rendered_block", sa.Text(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "(scope = 'TEAM' AND associated_user_id IS NULL) OR (scope = 'USER' AND "
            "associated_user_id IS NOT NULL)",
            name="ck_memory_units_scope",
        ),
        sa.CheckConstraint(
            "(accepted_at IS NULL AND markdown IS NULL AND rendered_block IS NULL) OR "
            "(accepted_at IS NOT NULL AND markdown IS NOT NULL AND rendered_block IS "
            "NOT NULL AND octet_length(rendered_block) <= 10000)",
            name="ck_memory_units_current_result",
        ),
        sa.ForeignKeyConstraint(
            ["active_session_id"], ["agent_sessions.id"], ondelete="SET NULL"
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
            "workspace_id",
            "agent_id",
            "scope",
            "associated_user_id",
            name="uq_memory_units_scope",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_memory_units_retry_at", "memory_units", ["retry_at"], unique=False
    )
    op.create_table(
        "memory_executions",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("unit_id", sa.String(length=32), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "execution_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("started_turns", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_tool_call_id", sa.String(length=256), nullable=True),
        sa.Column("rendered_bytes", sa.Integer(), nullable=True),
        sa.Column("settled_work_count", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(accepted_at IS NULL AND accepted_tool_call_id IS NULL AND "
            "rendered_bytes IS NULL AND settled_work_count IS NULL) OR (accepted_at "
            "IS NOT NULL AND accepted_tool_call_id IS NOT NULL AND rendered_bytes IS "
            "NOT NULL AND settled_work_count IS NOT NULL AND rendered_bytes BETWEEN 0 "
            "AND 10000 AND settled_work_count >= 0)",
            name="ck_memory_executions_accepted",
        ),
        sa.CheckConstraint("started_turns >= 0", name="ck_memory_executions_turns"),
        sa.ForeignKeyConstraint(["unit_id"], ["memory_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        "ix_memory_executions_unit_id", "memory_executions", ["unit_id"], unique=False
    )
    op.create_table(
        "memory_work",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("unit_id", sa.String(length=32), nullable=False),
        sa.Column("source_session_id", sa.String(length=32), nullable=False),
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
        sa.Column("admitted_session_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admitted_session_id"],
            ["memory_executions.session_id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["unit_id"], ["memory_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_work_admitted_session_id",
        "memory_work",
        ["admitted_session_id"],
        unique=False,
        postgresql_where=sa.text("admitted_session_id IS NOT NULL"),
    )
    op.create_index(
        "ix_memory_work_unit_pending",
        "memory_work",
        ["unit_id", "created_at", "id"],
        unique=False,
    )
    postgresql.ENUM(
        "provider_reported", "estimated", name="memory_legacy_cost_method"
    ).create(op.get_bind(), checkfirst=False)
    op.create_table(
        "memory_legacy_jobs",
        sa.Column("legacy_job_id", sa.String(length=32), nullable=False),
        sa.Column("unit_id", sa.String(length=32), nullable=False),
        sa.Column(
            "recorded_outcome",
            postgresql.ENUM(
                "RUNNING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "INVALIDATED",
                name="consolidation_attempt_state",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=120), nullable=True),
        sa.Column("model_requests", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("result_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rendered_bytes", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(result_published_at IS NULL AND rendered_bytes IS NULL) OR "
            "(result_published_at IS NOT NULL AND rendered_bytes IS NOT NULL)",
            name="ck_memory_legacy_jobs_publication",
        ),
        sa.CheckConstraint(
            "model_requests >= 0 AND tool_calls >= 0 AND input_tokens >= 0 AND "
            "output_tokens >= 0 AND (rendered_bytes IS NULL OR rendered_bytes BETWEEN "
            "0 AND 10000)",
            name="ck_memory_legacy_jobs_counts",
        ),
        sa.ForeignKeyConstraint(["unit_id"], ["memory_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("legacy_job_id"),
    )
    op.create_index(
        "ix_memory_legacy_jobs_unit_id", "memory_legacy_jobs", ["unit_id"], unique=False
    )
    op.create_table(
        "memory_legacy_model_usage",
        sa.Column("legacy_job_id", sa.String(length=32), nullable=False),
        sa.Column("legacy_dispatch_id", sa.String(length=32), nullable=False),
        sa.Column("request_number", sa.Integer(), nullable=False),
        sa.Column("reserved_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("reserved_output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("usage_recorded", sa.Boolean(), nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=True),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=True),
        sa.Column("total_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cached_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cache_creation_tokens", sa.BigInteger(), nullable=True),
        sa.Column("reasoning_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cost_usd", sa.Double(), nullable=True),
        sa.Column(
            "cost_method",
            postgresql.ENUM(
                "provider_reported",
                "estimated",
                name="memory_legacy_cost_method",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("cost_source_key", sa.Text(), nullable=True),
        sa.Column("cost_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cost_source_model_key", sa.Text(), nullable=True),
        sa.Column("cost_estimator_version", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(prompt_tokens IS NULL OR prompt_tokens >= 0) AND (completion_tokens IS "
            "NULL OR completion_tokens >= 0) AND (total_tokens IS NULL OR "
            "total_tokens >= 0) AND (cached_tokens IS NULL OR cached_tokens >= 0) AND "
            "(cache_creation_tokens IS NULL OR cache_creation_tokens >= 0) AND "
            "(reasoning_tokens IS NULL OR reasoning_tokens >= 0) AND (cost_usd IS "
            "NULL OR cost_usd >= 0)",
            name="ck_memory_legacy_usage_scalars",
        ),
        sa.CheckConstraint(
            "request_number >= 1 AND reserved_input_tokens >= 0 AND "
            "(reserved_output_tokens IS NULL OR reserved_output_tokens >= 1)",
            name="ck_memory_legacy_usage_reservation",
        ),
        sa.ForeignKeyConstraint(
            ["legacy_job_id"], ["memory_legacy_jobs.legacy_job_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("legacy_job_id", "legacy_dispatch_id"),
        sa.UniqueConstraint(
            "legacy_job_id", "request_number", name="uq_memory_legacy_usage_request"
        ),
    )

    # Retain only the selected current result; no historical result bodies are copied.
    op.execute(
        sa.text("""
        INSERT INTO memory_units
            (id, workspace_id, agent_id, scope, associated_user_id,
             markdown, rendered_block, accepted_at, retry_at, failure_count)
        SELECT u.id, u.workspace_id, u.agent_id, u.scope, u.associated_user_id,
               r.markdown, r.rendered_block, r.published_at, u.retry_at, u.failure_count
        FROM historical_consolidation_units u
        LEFT JOIN historical_consolidation_revisions r
          ON r.id = u.published_revision_id AND r.unit_id = u.id
    """)
    )
    # Work may have been registered before the first domain unit was created.
    op.execute(
        sa.text("""
        INSERT INTO memory_units
            (id, workspace_id, agent_id, scope, associated_user_id)
        SELECT replace(gen_random_uuid()::text, '-', ''), workspace_id,
               agent_id, scope, associated_user_id
        FROM (SELECT DISTINCT workspace_id, agent_id, scope, associated_user_id
              FROM historical_consolidation_work
              WHERE state IN ('PENDING', 'CONSIDERED')) pending
        ON CONFLICT ON CONSTRAINT uq_memory_units_scope DO NOTHING
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO memory_work (id, unit_id, source_session_id, kind, created_at)
        SELECT w.id, u.id, w.source_session_id, w.kind, w.created_at
        FROM historical_consolidation_work w
        JOIN memory_units u
          ON u.workspace_id = w.workspace_id AND u.agent_id = w.agent_id
         AND u.scope = w.scope
         AND u.associated_user_id IS NOT DISTINCT FROM w.associated_user_id
        WHERE w.state IN ('PENDING', 'CONSIDERED')
    """)
    )
    # Preserve truthful legacy job/usage scalars, without inventing a Session or submit.
    op.execute(
        sa.text("""
        INSERT INTO memory_legacy_jobs
            (legacy_job_id, unit_id, recorded_outcome, created_at, deadline_at,
             finished_at, failure_code, model_requests, tool_calls, input_tokens,
             output_tokens, result_published_at, rendered_bytes)
        SELECT a.id, a.unit_id, a.state, a.created_at, a.deadline_at, a.finished_at,
               a.failure_code, a.model_requests, a.tool_calls, a.input_tokens,
               a.output_tokens, r.published_at, octet_length(r.rendered_block)
        FROM historical_consolidation_attempts a
        LEFT JOIN historical_consolidation_revisions r
          ON r.id = a.completed_revision_id AND r.unit_id = a.unit_id
         AND r.attempt_id = a.id
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO memory_legacy_model_usage
            (legacy_job_id, legacy_dispatch_id, request_number,
             reserved_input_tokens, reserved_output_tokens, usage_recorded,
             prompt_tokens, completion_tokens, total_tokens, cached_tokens,
             cache_creation_tokens, reasoning_tokens, cost_usd, cost_method,
             cost_source_key, cost_collected_at, cost_source_model_key,
             cost_estimator_version)
        SELECT d.attempt_id, d.dispatch_id, d.request_number,
               d.reserved_input_tokens, d.reserved_output_tokens, d.usage_recorded,
               (d.usage_json ->> 'prompt_tokens')::bigint,
               (d.usage_json ->> 'completion_tokens')::bigint,
               (d.usage_json ->> 'total_tokens')::bigint,
               (d.usage_json ->> 'cached_tokens')::bigint,
               (d.usage_json ->> 'cache_creation_tokens')::bigint,
               (d.usage_json ->> 'reasoning_tokens')::bigint,
               (d.usage_json ->> 'cost_usd')::double precision,
               (d.usage_json ->> 'cost_method')::memory_legacy_cost_method,
               d.usage_json ->> 'cost_source_key',
               (d.usage_json ->> 'cost_collected_at')::timestamptz,
               d.usage_json ->> 'cost_source_model_key',
               d.usage_json ->> 'cost_estimator_version'
        FROM historical_consolidation_model_dispatches d
    """)
    )
    op.execute(
        sa.text("""
        DELETE FROM toolkit_states
        WHERE toolkit_namespace = 'memory' AND state_name = 'context_snapshot'
    """)
    )
    for table in (
        "historical_consolidation_draft_files",
        "historical_consolidation_draft_dependencies",
        "historical_consolidation_evidence",
        "historical_consolidation_mutation_receipts",
        "historical_consolidation_model_dispatches",
        "historical_consolidation_revision_dependencies",
        "historical_consolidation_drafts",
        "historical_consolidation_attempts",
        "historical_consolidation_revisions",
        "historical_consolidation_work",
        "historical_consolidation_units",
    ):
        op.drop_table(table)
    op.drop_constraint(
        "ck_historical_memory_sources_evidence_generations",
        "historical_memory_sources",
        type_="check",
    )
    op.drop_constraint(
        "ck_historical_memory_sources_evidence_hash",
        "historical_memory_sources",
        type_="check",
    )
    for column in ("summary_generation", "availability_generation", "evidence_hash"):
        op.drop_column("historical_memory_sources", column)
    op.drop_constraint(
        "uq_workspace_users_memory_grant_identity", "workspace_users", type_="unique"
    )
    op.drop_column("workspace_users", "memory_grant_identity")
    for name in (
        "consolidation_work_state",
        "consolidation_disposition",
    ):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    raise RuntimeError(
        "This migration is irreversible: obsolete authoring state was removed."
    )
