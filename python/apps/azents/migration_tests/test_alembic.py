"""Consolidated baseline invariants for the Azents RDB revision graph."""

import hashlib
import json

import pytest
import sqlalchemy as sa
import sqlalchemy.exc as sa_exc
from pytest_alembic import tests
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

from azents.rdb.models.base import RDBModel

_EXPECTED_PUBLIC_SCHEMA_FINGERPRINT = (
    "5dd5fa8b711996f58d1e84fa3c459ca9eea66c1500fe4a7d6a5fd7778b852cb4"
)


def _public_schema_fingerprint(connection: sa.Connection) -> str:
    """Return a stable fingerprint of the PostgreSQL public schema catalog."""
    rows = connection.execute(
        sa.text(
            r"""
            WITH entries AS (
                SELECT
                    'enum'::text AS category,
                    format(
                        '%I.%I[%s]',
                        namespace.nspname,
                        type.typname,
                        row_number() OVER (
                            PARTITION BY type.oid ORDER BY enum.enumsortorder
                        )
                    ) AS identity,
                    enum.enumlabel::text AS definition
                FROM pg_type AS type
                JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
                JOIN pg_enum AS enum ON enum.enumtypid = type.oid
                WHERE namespace.nspname = 'public'

                UNION ALL

                SELECT
                    'relation',
                    format('%I.%I', namespace.nspname, class.relname),
                    class.relkind::text
                FROM pg_class AS class
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'public'
                  AND class.relkind IN ('r', 'p', 'v', 'm', 'S')
                  AND class.relname <> 'alembic_version'

                UNION ALL

                SELECT
                    'column',
                    format('%I.%I.%I', namespace.nspname, class.relname,
                           attribute.attname),
                    concat_ws(
                        '|',
                        format_type(attribute.atttypid, attribute.atttypmod),
                        attribute.attnotnull::text,
                        COALESCE(pg_get_expr(default_value.adbin,
                                             default_value.adrelid), ''),
                        attribute.attidentity::text,
                        attribute.attgenerated::text
                    )
                FROM pg_attribute AS attribute
                JOIN pg_class AS class ON class.oid = attribute.attrelid
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                LEFT JOIN pg_attrdef AS default_value
                  ON default_value.adrelid = attribute.attrelid
                 AND default_value.adnum = attribute.attnum
                WHERE namespace.nspname = 'public'
                  AND class.relkind IN ('r', 'p', 'v', 'm')
                  AND class.relname <> 'alembic_version'
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped

                UNION ALL

                SELECT
                    'constraint',
                    format('%I.%I.%I', namespace.nspname, class.relname,
                           catalog_constraint.conname),
                    pg_get_constraintdef(catalog_constraint.oid, true)
                FROM pg_constraint AS catalog_constraint
                JOIN pg_class AS class ON class.oid = catalog_constraint.conrelid
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'public'
                  AND class.relname <> 'alembic_version'
                  AND catalog_constraint.contype <> 'n'

                UNION ALL

                SELECT
                    'index',
                    format('%I.%I', schemaname, indexname),
                    indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename <> 'alembic_version'

                UNION ALL

                SELECT
                    'function',
                    format('%I.%I(%s)', namespace.nspname, procedure.proname,
                           pg_get_function_identity_arguments(procedure.oid)),
                    pg_get_functiondef(procedure.oid)
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'public'

                UNION ALL

                SELECT
                    'trigger',
                    format('%I.%I.%I', namespace.nspname, class.relname,
                           trigger.tgname),
                    pg_get_triggerdef(trigger.oid, true)
                FROM pg_trigger AS trigger
                JOIN pg_class AS class ON class.oid = trigger.tgrelid
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'public'
                  AND NOT trigger.tgisinternal

                UNION ALL

                SELECT
                    'sequence',
                    format('%I.%I', namespace.nspname, class.relname),
                    concat_ws(
                        '|',
                        format_type(sequence.seqtypid, NULL),
                        sequence.seqstart::text,
                        sequence.seqincrement::text,
                        sequence.seqmax::text,
                        sequence.seqmin::text,
                        sequence.seqcache::text,
                        sequence.seqcycle::text
                    )
                FROM pg_sequence AS sequence
                JOIN pg_class AS class ON class.oid = sequence.seqrelid
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'public'

                UNION ALL

                SELECT
                    'policy',
                    format('%I.%I.%I', schemaname, tablename, policyname),
                    concat_ws(
                        '|',
                        permissive,
                        array_to_string(roles, ','),
                        cmd,
                        COALESCE(qual, ''),
                        COALESCE(with_check, '')
                    )
                FROM pg_policies
                WHERE schemaname = 'public'
            )
            SELECT category, identity, definition
            FROM entries
            ORDER BY category, identity, definition
            """
        )
    ).tuples()
    payload = json.dumps(
        [tuple(row) for row in rows], ensure_ascii=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def test_single_head_revision(alembic_runner: MigrationContext) -> None:
    """Require one deployable Alembic head."""
    tests.test_single_head_revision(alembic_runner)


def test_upgrade(alembic_runner: MigrationContext) -> None:
    """Require a complete base-to-head upgrade."""
    tests.test_upgrade(alembic_runner)


def test_all_check_constraints_are_named(
    alembic_runner: MigrationContext,
) -> None:
    """Keep named CHECK constraint autogeneration safe to enable."""
    alembic_runner.migrate_up_to("head")
    check_constraints = [
        constraint
        for table in RDBModel.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    ]

    assert check_constraints
    assert all(constraint.name is not None for constraint in check_constraints)


def test_selectable_model_candidate_chain_data_migration(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Lift legacy singular options and restore them on a safe downgrade."""
    alembic_runner.migrate_up_to("c05bc1b811fa")
    selection = {
        "llm_provider_integration_id": "integration-1",
        "provider": "openai",
        "model_identifier": "model-1",
    }
    legacy_options = [
        {
            "label": "default",
            "model_selection": selection,
            "settings": {
                "context_window_tokens": 32_000,
                "max_output_tokens": 4_000,
                "builtin_tools": [],
                "subagent_enabled": False,
                "subagent_guidance": "Use for focused work.",
            },
        }
    ]
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO workspaces (id, name, handle)
                VALUES ('workspace-1', 'Workspace', 'workspace')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO agents (
                    id, workspace_id, name, model_selection,
                    lightweight_model_selection, selectable_model_options,
                    main_model_label, lightweight_model_label
                )
                VALUES (
                    'agent-1', 'workspace-1', 'Agent',
                    CAST(:selection AS jsonb), CAST(:selection AS jsonb),
                    CAST(:options AS jsonb), 'default', 'default'
                )
                """
            ),
            {
                "selection": json.dumps(selection),
                "options": json.dumps(legacy_options),
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO workspace_model_settings (
                    workspace_id, default_model_selection,
                    default_lightweight_model_selection,
                    default_selectable_model_options,
                    default_main_model_label,
                    default_lightweight_model_label
                )
                VALUES (
                    'workspace-1', CAST(:selection AS jsonb),
                    CAST(:selection AS jsonb), CAST(:options AS jsonb),
                    'default', 'default'
                )
                """
            ),
            {
                "selection": json.dumps(selection),
                "options": json.dumps(legacy_options),
            },
        )

    alembic_runner.migrate_up_to("fae69c6c3540")
    with alembic_engine.connect() as connection:
        agent_options = connection.execute(
            sa.text("SELECT selectable_model_options FROM agents WHERE id = 'agent-1'")
        ).scalar_one()
        workspace_options = connection.execute(
            sa.text(
                """
                SELECT default_selectable_model_options
                FROM workspace_model_settings
                WHERE workspace_id = 'workspace-1'
                """
            )
        ).scalar_one()
        constraint_definition = connection.execute(
            sa.text(
                """
                SELECT pg_get_constraintdef(oid, true)
                FROM pg_constraint
                WHERE conname = 'ck_agents_selectable_model_options_shape'
                """
            )
        ).scalar_one()
        foundation_columns = set(
            connection.execute(
                sa.text(
                    """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND (
                        (table_name = 'agent_runs'
                         AND column_name = 'model_operation_state')
                        OR
                        (table_name = 'agent_sessions'
                         AND column_name IN (
                            'primary_model_reservation',
                            'title_model_operation_state'
                         ))
                      )
                    """
                )
            ).tuples()
        )
        cutover = connection.execute(
            sa.text(
                """
                SELECT schema_version, new_format_written_at
                FROM model_candidate_chain_cutovers
                WHERE id = 1
                """
            )
        ).one()
        health_table_exists = connection.execute(
            sa.text("SELECT to_regclass('public.model_candidate_health')")
        ).scalar_one()

    expected_options = [
        {
            "label": "default",
            "subagent_enabled": False,
            "subagent_guidance": "Use for focused work.",
            "candidates": [
                {
                    "model_selection": selection,
                    "settings": {
                        "context_window_tokens": 32_000,
                        "max_output_tokens": 4_000,
                        "builtin_tools": [],
                    },
                }
            ],
        }
    ]
    assert agent_options == expected_options
    assert workspace_options == expected_options
    assert '"candidates".size()' in constraint_definition
    assert foundation_columns == {
        ("agent_runs", "model_operation_state"),
        ("agent_sessions", "primary_model_reservation"),
        ("agent_sessions", "title_model_operation_state"),
    }
    assert cutover == (1, None)
    assert health_table_exists == "model_candidate_health"

    alembic_runner.migrate_down_to("c05bc1b811fa")
    with alembic_engine.connect() as connection:
        downgraded = connection.execute(
            sa.text("SELECT selectable_model_options FROM agents WHERE id = 'agent-1'")
        ).scalar_one()
    assert downgraded == legacy_options


def test_candidate_chain_downgrade_rejects_post_cutover_writes(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """The first canonical configuration write makes rollback fail closed."""
    alembic_runner.migrate_up_to("fae69c6c3540")
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                UPDATE model_candidate_chain_cutovers
                SET new_format_written_at = now()
                WHERE id = 1
                """
            )
        )

    with pytest.raises(
        sa_exc.DBAPIError,
        match="Cannot downgrade after canonical model configuration writes",
    ):
        alembic_runner.migrate_down_to("c05bc1b811fa")


def test_baseline_schema_and_seed_state(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Pin the pre-consolidation schema catalog and required singleton seeds."""
    alembic_runner.migrate_up_to("head")

    with alembic_engine.connect() as connection:
        assert _public_schema_fingerprint(connection) == (
            _EXPECTED_PUBLIC_SCHEMA_FINGERPRINT
        )
        file_lifecycle_settings = connection.execute(
            sa.text(
                """
                SELECT id, archived_session_retention_days,
                       updated_by_user_id, revision
                FROM system_file_lifecycle_settings
                """
            )
        ).one()
        assert file_lifecycle_settings == (1, 30, None, 1)

        runtime_cutover = connection.execute(
            sa.text(
                """
                SELECT allocator_version, cutover_at IS NOT NULL
                FROM runtime_connection_generation_cutovers
                """
            )
        ).one()
        assert runtime_cutover == (1, True)


def test_up_down_consistency(alembic_runner: MigrationContext) -> None:
    """Require the baseline to downgrade and upgrade consistently."""
    tests.test_up_down_consistency(alembic_runner)
