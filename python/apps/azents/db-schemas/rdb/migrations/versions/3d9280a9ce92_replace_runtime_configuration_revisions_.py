"""Replace immutable Runtime configuration revisions with current state."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3d9280a9ce92"
down_revision: str | Sequence[str] | None = "114473afc4be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Backfill bounded current authority and delete revision history."""
    bind = op.get_bind()
    state_status = postgresql.ENUM(
        "unconfigured",
        "blocked",
        "ready",
        name="runtime_configuration_state_status",
    )
    state_status.create(bind, checkfirst=True)

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM agent_runtimes AS runtime
                LEFT JOIN runtime_configuration_revisions AS revision
                  ON revision.id =
                     runtime.desired_runtime_configuration_revision_id
                WHERE runtime.desired_runtime_configuration_revision_id
                      IS NOT NULL
                  AND (
                      revision.id IS NULL
                      OR revision.runtime_id <> runtime.id
                  )
            ) THEN
                RAISE EXCEPTION
                    'runtime desired configuration pointer is invalid';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM agent_runtimes AS runtime
                LEFT JOIN runtime_configuration_revisions AS revision
                  ON revision.id =
                     runtime.applied_runtime_configuration_revision_id
                WHERE runtime.applied_runtime_configuration_revision_id
                      IS NOT NULL
                  AND (
                      revision.id IS NULL
                      OR revision.runtime_id <> runtime.id
                  )
            ) THEN
                RAISE EXCEPTION
                    'runtime applied configuration pointer is invalid';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM agent_runtimes AS runtime
                JOIN runtime_configuration_revisions AS revision
                  ON revision.id =
                     runtime.desired_runtime_configuration_revision_id
                WHERE revision.resolution_status = 'ready'
                  AND (
                      revision.digest IS NULL
                      OR revision.resolved_configuration IS NULL
                  )
            ) THEN
                RAISE EXCEPTION
                    'ready desired Runtime configuration is not convertible';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM agent_runtimes AS runtime
                JOIN runtime_configuration_revisions AS revision
                  ON revision.id =
                     runtime.applied_runtime_configuration_revision_id
                WHERE revision.resolution_status <> 'ready'
                   OR revision.digest IS NULL
                   OR revision.resolved_configuration IS NULL
            ) THEN
                RAISE EXCEPTION
                    'applied Runtime configuration is not convertible';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM agent_runtime_add_receipts AS receipt
                LEFT JOIN runtime_configuration_revisions AS revision
                  ON revision.id = receipt.runtime_configuration_revision_id
                LEFT JOIN agent_runtimes AS runtime
                  ON runtime.id = receipt.agent_runtime_id
                WHERE revision.id IS NULL
                   OR revision.runtime_id <> receipt.agent_runtime_id
                   OR (
                       revision.id <>
                           runtime.desired_runtime_configuration_revision_id
                       AND revision.id <>
                           runtime.applied_runtime_configuration_revision_id
                   )
            ) THEN
                RAISE EXCEPTION
                    'Runtime addition receipt evidence is not current';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM runtime_recreation_operation_items AS item
                LEFT JOIN runtime_configuration_revisions AS revision
                  ON revision.id = item.expected_configuration_revision_id
                LEFT JOIN agent_runtimes AS runtime
                  ON runtime.id = item.runtime_id
                WHERE revision.id IS NULL
                   OR revision.runtime_id <> item.runtime_id
                   OR (
                       item.status IN ('pending', 'running')
                       AND revision.id <>
                           runtime.desired_runtime_configuration_revision_id
                       AND revision.id <>
                           runtime.applied_runtime_configuration_revision_id
                   )
            ) THEN
                RAISE EXCEPTION
                    'active Runtime recreation evidence is not convertible';
            END IF;
        END
        $$;
        """
    )

    op.add_column(
        "agent_runtimes",
        sa.Column(
            "configuration_sequence",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_table(
        "runtime_configuration_states",
        sa.Column("runtime_id", sa.String(32), nullable=False),
        sa.Column("desired_sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "desired_status",
            postgresql.ENUM(
                "unconfigured",
                "blocked",
                "ready",
                name="runtime_configuration_state_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("desired_target_generation", sa.BigInteger(), nullable=False),
        sa.Column("desired_digest", sa.String(64), nullable=True),
        sa.Column("desired_document", postgresql.JSONB(), nullable=True),
        sa.Column("desired_reason_code", sa.String(120), nullable=True),
        sa.Column("provider_reported_digest", sa.String(64), nullable=True),
        sa.Column("runner_reported_digest", sa.String(64), nullable=True),
        sa.Column(
            "provider_acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "runner_observed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("applied_sequence", sa.BigInteger(), nullable=True),
        sa.Column(
            "applied_target_generation",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column("applied_digest", sa.String(64), nullable=True),
        sa.Column("applied_document", postgresql.JSONB(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "(desired_status = 'unconfigured' "
            "AND desired_digest IS NULL "
            "AND desired_document IS NULL "
            "AND desired_reason_code = 'runtime_profile_required') "
            "OR (desired_status = 'blocked' "
            "AND desired_reason_code IS NOT NULL) "
            "OR (desired_status = 'ready' "
            "AND desired_digest IS NOT NULL "
            "AND desired_document IS NOT NULL "
            "AND desired_reason_code IS NULL)",
            name="ck_runtime_configuration_states_desired",
        ),
        sa.CheckConstraint(
            "desired_sequence >= 1 "
            "AND (applied_sequence IS NULL OR applied_sequence >= 1)",
            name="ck_runtime_configuration_states_sequence",
        ),
        sa.CheckConstraint(
            "(applied_sequence IS NULL "
            "AND applied_target_generation IS NULL "
            "AND applied_digest IS NULL "
            "AND applied_document IS NULL "
            "AND applied_at IS NULL) "
            "OR (applied_sequence IS NOT NULL "
            "AND applied_target_generation IS NOT NULL "
            "AND applied_digest IS NOT NULL "
            "AND applied_document IS NOT NULL "
            "AND applied_at IS NOT NULL)",
            name="ck_runtime_configuration_states_applied",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_id"],
            ["agent_runtimes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("runtime_id"),
    )

    op.add_column(
        "agent_runtime_add_receipts",
        sa.Column(
            "runtime_configuration_sequence",
            sa.BigInteger(),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtime_add_receipts",
        sa.Column(
            "runtime_configuration_digest",
            sa.String(64),
            nullable=True,
        ),
    )
    op.add_column(
        "runtime_recreation_operation_items",
        sa.Column(
            "expected_configuration_sequence",
            sa.BigInteger(),
            nullable=True,
        ),
    )
    op.add_column(
        "runtime_recreation_operation_items",
        sa.Column(
            "expected_configuration_digest",
            sa.String(64),
            nullable=True,
        ),
    )
    op.add_column(
        "runtime_recreation_operation_items",
        sa.Column(
            "expected_desired_generation",
            sa.BigInteger(),
            nullable=True,
        ),
    )

    op.execute(
        """
        INSERT INTO runtime_configuration_states (
            runtime_id,
            desired_sequence,
            desired_status,
            desired_target_generation,
            desired_digest,
            desired_document,
            desired_reason_code,
            provider_reported_digest,
            runner_reported_digest,
            provider_acknowledged_at,
            runner_observed_at,
            applied_sequence,
            applied_target_generation,
            applied_digest,
            applied_document,
            applied_at
        )
        SELECT
            runtime.id,
            CASE
                WHEN applied.id IS NOT NULL
                 AND (desired.id IS NULL OR desired.id <> applied.id)
                    THEN 2
                ELSE 1
            END,
            CAST(
                CASE
                    WHEN desired.id IS NULL THEN 'unconfigured'
                    ELSE desired.resolution_status::text
                END
                AS runtime_configuration_state_status
            ),
            COALESCE(
                desired.target_desired_generation,
                runtime.desired_generation
            ),
            desired.digest,
            CASE
                WHEN desired.id IS NULL THEN NULL
                ELSE jsonb_build_object(
                    'schema_version', 1,
                    'source_trace', desired.source_trace,
                    'provider_id', desired.provider_id,
                    'provider_capability_revision_id',
                        desired.provider_capability_revision_id,
                    'infrastructure_profile_id',
                        desired.infrastructure_profile_id,
                    'infrastructure_profile_version',
                        desired.infrastructure_profile_version,
                    'workspace_runtime_profile_id',
                        desired.workspace_runtime_profile_id,
                    'workspace_runtime_profile_version',
                        desired.workspace_runtime_profile_version,
                    'agent_selection_version',
                        desired.agent_selection_version,
                    'required_capabilities',
                        desired.required_capabilities,
                    'missing_capabilities',
                        desired.missing_capabilities,
                    'resolved_configuration',
                        desired.resolved_configuration
                )
            END,
            CASE
                WHEN desired.id IS NULL THEN 'runtime_profile_required'
                ELSE desired.reason_code
            END,
            desired.provider_reported_digest,
            desired.runner_reported_digest,
            desired.provider_acknowledged_at,
            desired.runtime_observed_at,
            CASE WHEN applied.id IS NULL THEN NULL ELSE 1 END,
            applied.target_desired_generation,
            applied.digest,
            CASE
                WHEN applied.id IS NULL THEN NULL
                ELSE jsonb_build_object(
                    'schema_version', 1,
                    'source_trace', applied.source_trace,
                    'provider_id', applied.provider_id,
                    'provider_capability_revision_id',
                        applied.provider_capability_revision_id,
                    'infrastructure_profile_id',
                        applied.infrastructure_profile_id,
                    'infrastructure_profile_version',
                        applied.infrastructure_profile_version,
                    'workspace_runtime_profile_id',
                        applied.workspace_runtime_profile_id,
                    'workspace_runtime_profile_version',
                        applied.workspace_runtime_profile_version,
                    'agent_selection_version',
                        applied.agent_selection_version,
                    'required_capabilities',
                        applied.required_capabilities,
                    'missing_capabilities',
                        applied.missing_capabilities,
                    'resolved_configuration',
                        applied.resolved_configuration
                )
            END,
            CASE
                WHEN applied.id IS NULL THEN NULL
                ELSE COALESCE(
                    applied.runtime_observed_at,
                    applied.created_at
                )
            END
        FROM agent_runtimes AS runtime
        LEFT JOIN runtime_configuration_revisions AS desired
          ON desired.id =
             runtime.desired_runtime_configuration_revision_id
        LEFT JOIN runtime_configuration_revisions AS applied
          ON applied.id =
             runtime.applied_runtime_configuration_revision_id
        WHERE desired.id IS NOT NULL OR applied.id IS NOT NULL;
        """
    )
    op.execute(
        """
        UPDATE agent_runtimes AS runtime
        SET configuration_sequence = state.desired_sequence
        FROM runtime_configuration_states AS state
        WHERE state.runtime_id = runtime.id;
        """
    )
    op.execute(
        """
        UPDATE agent_runtime_add_receipts AS receipt
        SET runtime_configuration_sequence = CASE
                WHEN revision.id =
                     runtime.desired_runtime_configuration_revision_id
                    THEN state.desired_sequence
                ELSE state.applied_sequence
            END,
            runtime_configuration_digest = revision.digest
        FROM agent_runtimes AS runtime,
             runtime_configuration_states AS state,
             runtime_configuration_revisions AS revision
        WHERE runtime.id = receipt.agent_runtime_id
          AND state.runtime_id = runtime.id
          AND revision.id = receipt.runtime_configuration_revision_id;
        """
    )
    op.execute(
        """
        UPDATE runtime_recreation_operation_items AS item
        SET expected_configuration_sequence = CASE
                WHEN revision.id =
                     runtime.desired_runtime_configuration_revision_id
                    THEN state.desired_sequence
                WHEN revision.id =
                     runtime.applied_runtime_configuration_revision_id
                    THEN state.applied_sequence
                ELSE state.desired_sequence
            END,
            expected_configuration_digest = revision.digest,
            expected_desired_generation =
                revision.target_desired_generation
        FROM agent_runtimes AS runtime,
             runtime_configuration_states AS state,
             runtime_configuration_revisions AS revision
        WHERE runtime.id = item.runtime_id
          AND state.runtime_id = runtime.id
          AND revision.id = item.expected_configuration_revision_id;
        """
    )

    bind.execute(
        sa.text("""
            DO $$
            DECLARE
                item record;
            BEGIN
                FOR item IN
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'agent_runtimes'::regclass
                      AND contype = 'f'
                      AND (
                          pg_get_constraintdef(oid) LIKE
                              '%desired_runtime_configuration_revision_id%'
                          OR pg_get_constraintdef(oid) LIKE
                              '%applied_runtime_configuration_revision_id%'
                      )
                LOOP
                    EXECUTE format(
                        'ALTER TABLE agent_runtimes DROP CONSTRAINT %I',
                        item.conname
                    );
                END LOOP;

                FOR item IN
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'agent_runtime_add_receipts'::regclass
                      AND contype = 'f'
                      AND (
                          pg_get_constraintdef(oid) LIKE
                              '%workspace_runtime_profile_id%'
                          OR pg_get_constraintdef(oid) LIKE
                              '%runtime_configuration_revision_id%'
                      )
                LOOP
                    EXECUTE format(
                        'ALTER TABLE agent_runtime_add_receipts '
                        'DROP CONSTRAINT %I',
                        item.conname
                    );
                END LOOP;

                FOR item IN
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid =
                              'runtime_recreation_operation_items'::regclass
                      AND contype = 'f'
                      AND pg_get_constraintdef(oid) LIKE
                          '%expected_configuration_revision_id%'
                LOOP
                    EXECUTE format(
                        'ALTER TABLE runtime_recreation_operation_items '
                        'DROP CONSTRAINT %I',
                        item.conname
                    );
                END LOOP;
            END
            $$;
        """)
    )

    op.drop_column(
        "agent_runtime_add_receipts",
        "runtime_configuration_revision_id",
    )
    op.drop_column(
        "runtime_recreation_operation_items",
        "expected_configuration_revision_id",
    )
    op.alter_column(
        "agent_runtime_add_receipts",
        "runtime_configuration_sequence",
        nullable=False,
    )
    op.alter_column(
        "agent_runtime_add_receipts",
        "runtime_configuration_digest",
        nullable=False,
    )
    op.create_check_constraint(
        "ck_agent_runtime_add_receipts_configuration_sequence",
        "agent_runtime_add_receipts",
        "runtime_configuration_sequence >= 1",
    )
    op.alter_column(
        "runtime_recreation_operation_items",
        "expected_configuration_sequence",
        nullable=False,
    )
    op.alter_column(
        "runtime_recreation_operation_items",
        "expected_configuration_digest",
        nullable=False,
    )
    op.alter_column(
        "runtime_recreation_operation_items",
        "expected_desired_generation",
        nullable=False,
    )
    op.create_check_constraint(
        "ck_runtime_recreation_operation_items_expected_evidence",
        "runtime_recreation_operation_items",
        "expected_configuration_sequence >= 1 AND expected_desired_generation >= 0",
    )

    for index in (
        "ix_agent_runtimes_infrastructure_profile_id",
        "ix_agent_runtimes_workspace_runtime_profile_id",
    ):
        op.drop_index(index, table_name="agent_runtimes")
    for column in (
        "infrastructure_profile_id",
        "workspace_runtime_profile_id",
        "desired_runtime_configuration_revision_id",
        "applied_runtime_configuration_revision_id",
    ):
        op.drop_column("agent_runtimes", column)

    op.drop_table("runtime_configuration_revisions")
    op.execute("DROP TYPE runtime_configuration_resolution_status")


def downgrade() -> None:
    """Reconstruct only current desired/applied revision evidence."""
    bind = op.get_bind()
    resolution_status = postgresql.ENUM(
        "ready",
        "blocked",
        name="runtime_configuration_resolution_status",
    )
    resolution_status.create(bind, checkfirst=True)

    op.create_table(
        "runtime_configuration_revisions",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("runtime_id", sa.String(32), nullable=False),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column(
            "provider_capability_revision_id",
            sa.String(32),
            nullable=True,
        ),
        sa.Column("infrastructure_profile_id", sa.String(32), nullable=False),
        sa.Column("infrastructure_profile_version", sa.Integer(), nullable=False),
        sa.Column("workspace_runtime_profile_id", sa.String(32), nullable=False),
        sa.Column(
            "workspace_runtime_profile_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("agent_selection_version", sa.Integer(), nullable=False),
        sa.Column(
            "resolution_status",
            postgresql.ENUM(
                "ready",
                "blocked",
                name="runtime_configuration_resolution_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("required_capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("missing_capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("source_trace", postgresql.JSONB(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("target_desired_generation", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(120), nullable=True),
        sa.Column("resolved_configuration", postgresql.JSONB(), nullable=True),
        sa.Column("provider_reported_digest", sa.String(64), nullable=True),
        sa.Column("runner_reported_digest", sa.String(64), nullable=True),
        sa.Column(
            "provider_acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "runtime_observed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "(resolution_status = 'ready' "
            "AND resolved_configuration IS NOT NULL "
            "AND reason_code IS NULL) "
            "OR (resolution_status = 'blocked' "
            "AND resolved_configuration IS NULL "
            "AND reason_code IS NOT NULL)",
            name="ck_runtime_configuration_revisions_resolution_document",
        ),
        sa.CheckConstraint(
            "target_desired_generation >= 0",
            name="ck_runtime_configuration_revisions_target_generation",
        ),
        sa.CheckConstraint(
            "agent_selection_version >= 1",
            name="ck_runtime_configuration_revisions_agent_selection_version",
        ),
        sa.CheckConstraint(
            "resolution_status = 'blocked' "
            "OR provider_capability_revision_id IS NOT NULL",
            name="ck_runtime_configuration_revisions_ready_capability",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_id"],
            ["agent_runtimes.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["runtime_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_capability_revision_id"],
            ["runtime_provider_contract_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["infrastructure_profile_id"],
            ["runtime_infrastructure_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_runtime_profile_id"],
            ["workspace_runtime_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "runtime_id",
            "digest",
            "target_desired_generation",
            name="uq_runtime_configuration_revisions_runtime_digest_generation",
        ),
    )
    op.create_index(
        "ix_runtime_configuration_revisions_runtime_created",
        "runtime_configuration_revisions",
        ["runtime_id", "created_at"],
    )
    op.create_index(
        "ix_runtime_configuration_revisions_provider_id",
        "runtime_configuration_revisions",
        ["provider_id"],
    )
    op.create_index(
        "ix_runtime_configuration_revisions_workspace_profile",
        "runtime_configuration_revisions",
        ["workspace_runtime_profile_id"],
    )

    op.add_column(
        "agent_runtimes",
        sa.Column("infrastructure_profile_id", sa.String(32), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("workspace_runtime_profile_id", sa.String(32), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "desired_runtime_configuration_revision_id",
            sa.String(32),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "applied_runtime_configuration_revision_id",
            sa.String(32),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtime_add_receipts",
        sa.Column(
            "runtime_configuration_revision_id",
            sa.String(32),
            nullable=True,
        ),
    )
    op.add_column(
        "runtime_recreation_operation_items",
        sa.Column(
            "expected_configuration_revision_id",
            sa.String(32),
            nullable=True,
        ),
    )

    op.execute(
        """
        INSERT INTO runtime_configuration_revisions (
            id, runtime_id, provider_id,
            provider_capability_revision_id,
            infrastructure_profile_id,
            infrastructure_profile_version,
            workspace_runtime_profile_id,
            workspace_runtime_profile_version,
            agent_selection_version, resolution_status,
            required_capabilities, missing_capabilities,
            source_trace, digest, target_desired_generation,
            reason_code, resolved_configuration,
            provider_reported_digest, runner_reported_digest,
            provider_acknowledged_at, runtime_observed_at
        )
        SELECT
            md5(state.runtime_id || chr(58) || 'desired'),
            state.runtime_id,
            state.desired_document->>'provider_id',
            state.desired_document->>'provider_capability_revision_id',
            state.desired_document->>'infrastructure_profile_id',
            (state.desired_document->>'infrastructure_profile_version')::integer,
            state.desired_document->>'workspace_runtime_profile_id',
            (state.desired_document->>'workspace_runtime_profile_version')::integer,
            (state.desired_document->>'agent_selection_version')::integer,
            CAST(
                state.desired_status::text
                AS runtime_configuration_resolution_status
            ),
            state.desired_document->'required_capabilities',
            state.desired_document->'missing_capabilities',
            state.desired_document->'source_trace',
            state.desired_digest,
            state.desired_target_generation,
            state.desired_reason_code,
            state.desired_document->'resolved_configuration',
            state.provider_reported_digest,
            state.runner_reported_digest,
            state.provider_acknowledged_at,
            state.runner_observed_at
        FROM runtime_configuration_states AS state
        WHERE state.desired_document IS NOT NULL;
        """
    )
    op.execute(
        """
        INSERT INTO runtime_configuration_revisions (
            id, runtime_id, provider_id,
            provider_capability_revision_id,
            infrastructure_profile_id,
            infrastructure_profile_version,
            workspace_runtime_profile_id,
            workspace_runtime_profile_version,
            agent_selection_version, resolution_status,
            required_capabilities, missing_capabilities,
            source_trace, digest, target_desired_generation,
            reason_code, resolved_configuration,
            provider_reported_digest, runner_reported_digest,
            provider_acknowledged_at, runtime_observed_at
        )
        SELECT
            md5(state.runtime_id || chr(58) || 'applied'),
            state.runtime_id,
            state.applied_document->>'provider_id',
            state.applied_document->>'provider_capability_revision_id',
            state.applied_document->>'infrastructure_profile_id',
            (state.applied_document->>'infrastructure_profile_version')::integer,
            state.applied_document->>'workspace_runtime_profile_id',
            (state.applied_document->>'workspace_runtime_profile_version')::integer,
            (state.applied_document->>'agent_selection_version')::integer,
            CAST('ready' AS runtime_configuration_resolution_status),
            state.applied_document->'required_capabilities',
            state.applied_document->'missing_capabilities',
            state.applied_document->'source_trace',
            state.applied_digest,
            state.applied_target_generation,
            NULL,
            state.applied_document->'resolved_configuration',
            state.applied_digest,
            state.applied_digest,
            state.applied_at,
            state.applied_at
        FROM runtime_configuration_states AS state
        WHERE state.applied_document IS NOT NULL
          AND state.applied_sequence <> state.desired_sequence;
        """
    )
    op.execute(
        """
        UPDATE agent_runtimes AS runtime
        SET infrastructure_profile_id =
                COALESCE(
                    state.desired_document,
                    state.applied_document
                )->>'infrastructure_profile_id',
            workspace_runtime_profile_id =
                COALESCE(
                    state.desired_document,
                    state.applied_document
                )->>'workspace_runtime_profile_id',
            desired_runtime_configuration_revision_id = CASE
                WHEN state.desired_document IS NULL THEN NULL
                ELSE md5(state.runtime_id || chr(58) || 'desired')
            END,
            applied_runtime_configuration_revision_id = CASE
                WHEN state.applied_document IS NULL THEN NULL
                WHEN state.applied_sequence = state.desired_sequence
                    THEN md5(state.runtime_id || chr(58) || 'desired')
                ELSE md5(state.runtime_id || chr(58) || 'applied')
            END
        FROM runtime_configuration_states AS state
        WHERE state.runtime_id = runtime.id;
        """
    )
    op.execute(
        """
        UPDATE agent_runtime_add_receipts AS receipt
        SET runtime_configuration_revision_id = CASE
                WHEN receipt.runtime_configuration_sequence =
                     state.desired_sequence
                 AND receipt.runtime_configuration_digest =
                     state.desired_digest
                    THEN md5(state.runtime_id || chr(58) || 'desired')
                ELSE md5(state.runtime_id || chr(58) || 'applied')
            END
        FROM runtime_configuration_states AS state
        WHERE state.runtime_id = receipt.agent_runtime_id;
        """
    )
    op.execute(
        """
        UPDATE runtime_recreation_operation_items AS item
        SET expected_configuration_revision_id = CASE
                WHEN item.expected_configuration_sequence =
                     state.desired_sequence
                 AND item.expected_configuration_digest =
                     state.desired_digest
                 AND item.expected_desired_generation =
                     state.desired_target_generation
                 AND state.desired_document IS NOT NULL
                    THEN md5(state.runtime_id || chr(58) || 'desired')
                WHEN item.expected_configuration_sequence =
                     state.applied_sequence
                 AND item.expected_configuration_digest =
                     state.applied_digest
                 AND item.expected_desired_generation =
                     state.applied_target_generation
                    THEN CASE
                        WHEN state.applied_sequence = state.desired_sequence
                            THEN md5(state.runtime_id || chr(58) || 'desired')
                        ELSE md5(state.runtime_id || chr(58) || 'applied')
                    END
                ELSE md5(state.runtime_id || chr(58) || 'desired')
            END
        FROM runtime_configuration_states AS state
        WHERE state.runtime_id = item.runtime_id;
        """
    )

    op.alter_column(
        "agent_runtime_add_receipts",
        "runtime_configuration_revision_id",
        nullable=False,
    )
    op.alter_column(
        "runtime_recreation_operation_items",
        "expected_configuration_revision_id",
        nullable=False,
    )
    op.create_index(
        "ix_agent_runtimes_infrastructure_profile_id",
        "agent_runtimes",
        ["infrastructure_profile_id"],
    )
    op.create_index(
        "ix_agent_runtimes_workspace_runtime_profile_id",
        "agent_runtimes",
        ["workspace_runtime_profile_id"],
    )
    op.create_foreign_key(
        "fk_agent_runtimes_infrastructure_profile_id",
        "agent_runtimes",
        "runtime_infrastructure_profiles",
        ["infrastructure_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agent_runtimes_workspace_runtime_profile_id",
        "agent_runtimes",
        "workspace_runtime_profiles",
        ["workspace_runtime_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agent_runtimes_desired_runtime_configuration_revision_id",
        "agent_runtimes",
        "runtime_configuration_revisions",
        ["desired_runtime_configuration_revision_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_foreign_key(
        "fk_agent_runtimes_applied_runtime_configuration_revision_id",
        "agent_runtimes",
        "runtime_configuration_revisions",
        ["applied_runtime_configuration_revision_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_foreign_key(
        None,
        "agent_runtime_add_receipts",
        "workspace_runtime_profiles",
        ["workspace_runtime_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        None,
        "agent_runtime_add_receipts",
        "runtime_configuration_revisions",
        ["runtime_configuration_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        None,
        "runtime_recreation_operation_items",
        "runtime_configuration_revisions",
        ["expected_configuration_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "ck_agent_runtime_add_receipts_configuration_sequence",
        "agent_runtime_add_receipts",
        type_="check",
    )
    op.drop_constraint(
        "ck_runtime_recreation_operation_items_expected_evidence",
        "runtime_recreation_operation_items",
        type_="check",
    )
    op.drop_column("agent_runtimes", "configuration_sequence")
    op.drop_column(
        "agent_runtime_add_receipts",
        "runtime_configuration_sequence",
    )
    op.drop_column(
        "agent_runtime_add_receipts",
        "runtime_configuration_digest",
    )
    op.drop_column(
        "runtime_recreation_operation_items",
        "expected_configuration_sequence",
    )
    op.drop_column(
        "runtime_recreation_operation_items",
        "expected_configuration_digest",
    )
    op.drop_column(
        "runtime_recreation_operation_items",
        "expected_desired_generation",
    )
    op.drop_table("runtime_configuration_states")
    op.execute("DROP TYPE runtime_configuration_state_status")
