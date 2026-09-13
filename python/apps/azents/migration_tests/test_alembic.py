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
    "122064b212e8158c6e94124553482d83658665b28f7f31e9ed2d77a64e44df24"
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


def test_runtime_web_epoch_removal_discards_stale_auth_authority(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Keep records rejected by the prior active epoch rejected after migration."""
    alembic_runner.migrate_up_to("a779d057128b")
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                UPDATE runtime_web_auth_configuration
                SET active_epoch = 2
                WHERE id = 1
                """
            )
        )
        connection.execute(sa.text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            sa.text(
                """
                INSERT INTO runtime_web_gateway_identities (
                    id,
                    secret_hash,
                    user_id,
                    auth_session_id,
                    mode,
                    epoch,
                    browser_profile,
                    issued_at,
                    expires_at
                )
                VALUES
                    (
                        'stale-runtime-web-identity',
                        repeat('a', 64),
                        'migration-user',
                        'migration-auth-session',
                        'separate_domain',
                        1,
                        'chromium-152',
                        now() - interval '1 minute',
                        now() + interval '1 hour'
                    ),
                    (
                        'current-runtime-web-identity',
                        repeat('b', 64),
                        'migration-user',
                        'migration-auth-session',
                        'separate_domain',
                        2,
                        'chromium-152',
                        now() - interval '1 minute',
                        now() + interval '1 hour'
                    )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO runtime_web_auth_bindings (
                    id,
                    initiation_id,
                    main_binding_hash,
                    user_id,
                    auth_session_id,
                    endpoint_id,
                    epoch,
                    expires_at
                )
                VALUES
                    (
                        'stale-runtime-web-binding',
                        'stale-runtime-web-initiation',
                        repeat('c', 64),
                        'migration-user',
                        'migration-auth-session',
                        'migration-runtime-endpoint',
                        1,
                        now() + interval '1 hour'
                    ),
                    (
                        'current-runtime-web-binding',
                        'current-runtime-web-initiation',
                        repeat('d', 64),
                        'migration-user',
                        'migration-auth-session',
                        'migration-runtime-endpoint',
                        2,
                        now() + interval '1 hour'
                    )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO runtime_web_auth_tickets (
                    id,
                    binding_id,
                    secret_hash,
                    user_id,
                    auth_session_id,
                    endpoint_id,
                    epoch,
                    issued_at,
                    expires_at
                )
                VALUES
                    (
                        'stale-runtime-web-ticket',
                        'stale-runtime-web-binding',
                        repeat('e', 64),
                        'migration-user',
                        'migration-auth-session',
                        'migration-runtime-endpoint',
                        1,
                        now(),
                        now() + interval '5 minutes'
                    ),
                    (
                        'current-runtime-web-ticket',
                        'current-runtime-web-binding',
                        repeat('f', 64),
                        'migration-user',
                        'migration-auth-session',
                        'migration-runtime-endpoint',
                        2,
                        now(),
                        now() + interval '5 minutes'
                    )
                """
            )
        )

    alembic_runner.migrate_up_to("head")

    with alembic_engine.connect() as connection:
        identity_revocation = {
            row.id: row.revoked
            for row in connection.execute(
                sa.text(
                    """
                    SELECT id, revoked_at IS NOT NULL AS revoked
                    FROM runtime_web_gateway_identities
                    WHERE id IN (
                        'stale-runtime-web-identity',
                        'current-runtime-web-identity'
                    )
                    """
                )
            ).mappings()
        }
        binding_ids = set(
            connection.execute(
                sa.text(
                    """
                    SELECT id
                    FROM runtime_web_auth_bindings
                    WHERE id IN (
                        'stale-runtime-web-binding',
                        'current-runtime-web-binding'
                    )
                    """
                )
            ).scalars()
        )
        ticket_ids = set(
            connection.execute(
                sa.text(
                    """
                    SELECT id
                    FROM runtime_web_auth_tickets
                    WHERE id IN (
                        'stale-runtime-web-ticket',
                        'current-runtime-web-ticket'
                    )
                    """
                )
            ).scalars()
        )

    assert identity_revocation == {
        "stale-runtime-web-identity": True,
        "current-runtime-web-identity": False,
    }
    assert binding_ids == {"current-runtime-web-binding"}
    assert ticket_ids == {"current-runtime-web-ticket"}


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


def test_session_model_settings_candidate_data_migration(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Remove legacy option fields from Session candidate settings."""
    alembic_runner.migrate_up_to("e767c81c6ed9")
    selection = {
        "llm_provider_integration_id": "integration-1",
        "provider": "openai",
        "model_identifier": "model-1",
    }
    candidate_settings = {
        "context_window_tokens": 32_000,
        "max_output_tokens": 4_000,
        "builtin_tools": [],
    }
    guidance = "Use for focused work."
    options = [
        {
            "label": "default",
            "subagent_enabled": False,
            "subagent_guidance": guidance,
            "candidates": [
                {
                    "model_selection": selection,
                    "settings": candidate_settings,
                }
            ],
        }
    ]
    legacy_session_settings = {
        **candidate_settings,
        "subagent_enabled": False,
        "subagent_guidance": guidance,
    }
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO workspaces (id, name, handle)
                VALUES ('session-workspace', 'Session Workspace', 'session-workspace')
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
                    'session-agent', 'session-workspace', 'Session Agent',
                    CAST(:selection AS jsonb), CAST(:selection AS jsonb),
                    CAST(:options AS jsonb), 'default', 'default'
                )
                """
            ),
            {
                "selection": json.dumps(selection),
                "options": json.dumps(options),
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO agent_sessions (
                    id, workspace_id, agent_id, handle,
                    current_model_target_label, current_model_selection,
                    current_model_settings,
                    current_effective_context_window_tokens,
                    current_effective_auto_compaction_threshold_tokens,
                    current_inference_resolved_at,
                    session_kind, product_mode, status, start_reason
                )
                VALUES (
                    'legacy-session', 'session-workspace', 'session-agent',
                    'legacy-session', 'default', CAST(:selection AS jsonb),
                    CAST(:settings AS jsonb), 32000, 28000, now(),
                    'root', 'team', 'active', 'initial'
                )
                """
            ),
            {
                "selection": json.dumps(selection),
                "settings": json.dumps(legacy_session_settings),
            },
        )

    alembic_runner.migrate_up_to("head")
    with alembic_engine.connect() as connection:
        migrated = connection.execute(
            sa.text(
                """
                SELECT current_model_settings
                FROM agent_sessions
                WHERE id = 'legacy-session'
                """
            )
        ).scalar_one()
    assert migrated == candidate_settings

    alembic_runner.migrate_down_to("e767c81c6ed9")
    with alembic_engine.connect() as connection:
        downgraded = connection.execute(
            sa.text(
                """
                SELECT current_model_settings
                FROM agent_sessions
                WHERE id = 'legacy-session'
                """
            )
        ).scalar_one()
    assert downgraded == legacy_session_settings


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
        browser_profile_column = connection.execute(
            sa.text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'runtime_web_gateway_identities'
                  AND column_name = 'browser_profile'
                """
            )
        ).one_or_none()
        assert browser_profile_column is None
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

        runtime_web_configuration = connection.execute(
            sa.text(
                """
                SELECT enabled, mode, active_duration_seconds
                FROM runtime_web_auth_configuration
                """
            )
        ).one()
        assert runtime_web_configuration == (
            False,
            "separate_domain",
            7_200,
        )
        runtime_web_pointer_constraints = set(
            connection.execute(
                sa.text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'runtime_web_endpoints'::regclass
                      AND contype = 'f'
                      AND conname LIKE 'fk_runtime_web_endpoints_current_%'
                    """
                )
            ).scalars()
        )
        assert runtime_web_pointer_constraints == {
            "fk_runtime_web_endpoints_current_cycle",
            "fk_runtime_web_endpoints_current_pending",
        }


def test_up_down_consistency(alembic_runner: MigrationContext) -> None:
    """Require the baseline to downgrade and upgrade consistently."""
    tests.test_up_down_consistency(alembic_runner)
