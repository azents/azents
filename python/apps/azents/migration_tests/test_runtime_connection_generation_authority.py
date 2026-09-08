"""Migration tests for durable Runtime connection-generation authority."""

import pytest
import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT_REVISION = "4ab7015e39b5"
_FOUNDATION_REVISION = "fa67b82b0b53"
_ACTIVATION_REVISION = "afd1289d7982"
_LEGACY_CUTOVER_HIGH_WATER = 2**48 - 1


def _seed_existing_subjects(connection: sa.Connection) -> None:
    """Insert Provider and Runtime subjects with durable generation evidence."""
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('generation-workspace', 'Generation Workspace', 'generation')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO runtime_providers (
              id, provider_id, scope, kind, display_name, registration_method,
              enabled, lifecycle_state, availability_mode, admin_version,
              capabilities
            ) VALUES (
              'generation-provider', 'generation-provider-logical', 'system',
              'docker', 'Generation Provider', 'admin', true, 'active',
              'platform_wide', 0, '{}'::jsonb
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO runtime_provider_auth_bindings (
              id, provider_id, auth_method, subject, state, owner
            ) VALUES (
              'generation-binding', 'generation-provider',
              'azents_issued_token', 'admin:generation-provider',
              'active', 'admin'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO runtime_provider_connections (
              id, provider_id, binding_id, credential_id, auth_method,
              auth_subject, evidence_expires_at, connection_id, generation,
              status, reported_provider_type, reported_protocol_version,
              operational_diagnostics, diagnostics_checked_at,
              connected_at, last_heartbeat_at, disconnected_at
            ) VALUES (
              'generation-connection', 'generation-provider',
              'generation-binding', NULL, 'azents_issued_token',
              'admin:generation-provider', NULL, 'generation-connection-id', 7,
              'connected', 'docker', 'runtime-provider-v1', NULL, NULL,
              now(), now(), NULL
            )
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
            ) VALUES (
              'generation-agent', 'generation-workspace', 'Generation Agent',
              '{}'::jsonb, '{}'::jsonb,
              '[{"label": "default", "model_selection": {}}]'::jsonb,
              'default', 'default'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_runtimes (
              id, workspace_id, agent_id, runtime_provider_id,
              runtime_provider_resource_id, provider_binding_origin,
              desired_generation, provider_generation, runner_generation
            ) VALUES (
              'generation-runtime', 'generation-workspace', 'generation-agent',
              'generation-provider-logical', 'generation-provider',
              'agent_explicit', 3, 7, 11
            )
            """
        )
    )


def test_foundation_widens_generation_columns_without_activating_cutover(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """The additive migration preserves values and leaves authority unseeded."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_existing_subjects(connection)

    alembic_runner.migrate_up_to(_FOUNDATION_REVISION)

    with alembic_engine.connect() as connection:
        authority_count = connection.scalar(
            sa.text("SELECT COUNT(*) FROM runtime_connection_generations")
        )
        cutover_count = connection.scalar(
            sa.text("SELECT COUNT(*) FROM runtime_connection_generation_cutovers")
        )
        assert authority_count == 0
        assert cutover_count == 0

        generations = (
            connection.execute(
                sa.text(
                    """
                    SELECT
                      (SELECT generation FROM runtime_provider_connections
                       WHERE id = 'generation-connection') AS provider_connection,
                      provider_generation,
                      runner_generation
                    FROM agent_runtimes
                    WHERE id = 'generation-runtime'
                    """
                )
            )
            .mappings()
            .one()
        )
        assert generations == {
            "provider_connection": 7,
            "provider_generation": 7,
            "runner_generation": 11,
        }

        column_rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT table_name || '.' || column_name AS qualified_name,
                           data_type
                    FROM information_schema.columns
                    WHERE (table_name, column_name) IN (
                      ('runtime_provider_connections', 'generation'),
                      ('agent_runtimes', 'provider_generation'),
                      ('agent_runtimes', 'runner_generation')
                    )
                    """
                )
            )
            .mappings()
            .all()
        )
        column_types = {
            str(row["qualified_name"]): str(row["data_type"]) for row in column_rows
        }
        assert column_types == {
            "agent_runtimes.provider_generation": "bigint",
            "agent_runtimes.runner_generation": "bigint",
            "runtime_provider_connections.generation": "bigint",
        }


def test_subject_created_after_foundation_is_not_preallocated(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """A subject inserted after foundation migration remains unseeded."""
    alembic_runner.migrate_up_to(_FOUNDATION_REVISION)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO runtime_providers (
                  id, provider_id, scope, kind, display_name, registration_method,
                  enabled, lifecycle_state, availability_mode, admin_version,
                  capabilities
                ) VALUES (
                  'post-cutover-provider', 'post-cutover-provider-logical',
                  'system', 'docker', 'Post-cutover Provider', 'admin', true,
                  'active', 'platform_wide', 0, '{}'::jsonb
                )
                """
            )
        )
        count = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM runtime_connection_generations
                WHERE connection_kind = 'provider'
                  AND subject_id = 'post-cutover-provider'
                """
            )
        )
        assert count == 0


def test_foundation_downgrade_rejects_accepted_authority_above_integer(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Rollback cannot discard accepted authority absent from legacy projections."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_existing_subjects(connection)
    alembic_runner.migrate_up_to(_FOUNDATION_REVISION)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO runtime_connection_generations (
                  connection_kind,
                  subject_id,
                  high_water_generation,
                  accepted_generation
                ) VALUES (
                  'runner',
                  'generation-runtime',
                  :generation,
                  :generation
                )
                """
            ),
            {"generation": 2**31},
        )

    with pytest.raises(
        RuntimeError,
        match="accepted Runtime connection authority or projection exceeds INTEGER",
    ):
        alembic_runner.migrate_down_to(_PARENT_REVISION)


def test_activation_seeds_existing_subjects_and_records_cutover(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Activation places every legacy-capable subject in the safe generation band."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_existing_subjects(connection)

    alembic_runner.migrate_up_to(_ACTIVATION_REVISION)

    with alembic_engine.connect() as connection:
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT connection_kind, subject_id, high_water_generation,
                           accepted_generation
                    FROM runtime_connection_generations
                    ORDER BY connection_kind, subject_id
                    """
                )
            )
            .mappings()
            .all()
        )
        assert [dict(row) for row in rows] == [
            {
                "connection_kind": "provider",
                "subject_id": "generation-provider",
                "high_water_generation": _LEGACY_CUTOVER_HIGH_WATER,
                "accepted_generation": 7,
            },
            {
                "connection_kind": "runner",
                "subject_id": "generation-runtime",
                "high_water_generation": _LEGACY_CUTOVER_HIGH_WATER,
                "accepted_generation": 11,
            },
        ]
        marker = (
            connection.execute(
                sa.text(
                    """
                    SELECT allocator_version, cutover_at
                    FROM runtime_connection_generation_cutovers
                    """
                )
            )
            .mappings()
            .one()
        )
        assert marker["allocator_version"] == 1
        assert marker["cutover_at"] is not None
        trigger_names = set(
            connection.scalars(
                sa.text(
                    """
                    SELECT tgname
                    FROM pg_trigger
                    WHERE NOT tgisinternal
                      AND tgname IN (
                        'trg_runtime_providers_connection_generation',
                        'trg_agent_runtimes_connection_generation'
                      )
                    """
                )
            )
        )
        assert trigger_names == {
            "trg_runtime_providers_connection_generation",
            "trg_agent_runtimes_connection_generation",
        }


def test_activation_triggers_initialize_future_subjects(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Subjects inserted after activation atomically receive zeroed authority."""
    alembic_runner.migrate_up_to(_ACTIVATION_REVISION)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO workspaces (id, name, handle)
                VALUES (
                  'future-generation-workspace',
                  'Future Generation Workspace',
                  'future-generation'
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO runtime_providers (
                  id, provider_id, scope, kind, display_name, registration_method,
                  enabled, lifecycle_state, availability_mode, admin_version,
                  capabilities
                ) VALUES (
                  'future-generation-provider',
                  'future-generation-provider-logical',
                  'system', 'docker', 'Future Generation Provider', 'admin',
                  true, 'active', 'platform_wide', 0, '{}'::jsonb
                )
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
                ) VALUES (
                  'future-generation-agent',
                  'future-generation-workspace',
                  'Future Generation Agent',
                  '{}'::jsonb,
                  '{}'::jsonb,
                  '[{"label": "default", "model_selection": {}}]'::jsonb,
                  'default',
                  'default'
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO agent_runtimes (
                  id, workspace_id, agent_id, runtime_provider_id,
                  runtime_provider_resource_id, provider_binding_origin,
                  desired_generation
                ) VALUES (
                  'future-generation-runtime',
                  'future-generation-workspace',
                  'future-generation-agent',
                  'future-generation-provider-logical',
                  'future-generation-provider',
                  'agent_explicit',
                  1
                )
                """
            )
        )
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT connection_kind, subject_id, high_water_generation,
                           accepted_generation
                    FROM runtime_connection_generations
                    WHERE subject_id IN (
                      'future-generation-provider',
                      'future-generation-runtime'
                    )
                    ORDER BY connection_kind
                    """
                )
            )
            .mappings()
            .all()
        )
        assert [dict(row) for row in rows] == [
            {
                "connection_kind": "provider",
                "subject_id": "future-generation-provider",
                "high_water_generation": 0,
                "accepted_generation": 0,
            },
            {
                "connection_kind": "runner",
                "subject_id": "future-generation-runtime",
                "high_water_generation": 0,
                "accepted_generation": 0,
            },
        ]


def test_activation_downgrade_rejects_started_allocation(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Rollback is forbidden once any post-cutover allocation has started."""
    alembic_runner.migrate_up_to(_ACTIVATION_REVISION)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO runtime_providers (
                  id, provider_id, scope, kind, display_name, registration_method,
                  enabled, lifecycle_state, availability_mode, admin_version,
                  capabilities
                ) VALUES (
                  'allocated-generation-provider',
                  'allocated-generation-provider-logical',
                  'system', 'docker', 'Allocated Generation Provider', 'admin',
                  true, 'active', 'platform_wide', 0, '{}'::jsonb
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                UPDATE runtime_connection_generations
                SET high_water_generation = 1
                WHERE connection_kind = 'provider'
                  AND subject_id = 'allocated-generation-provider'
                """
            )
        )

    with pytest.raises(
        RuntimeError,
        match="Runtime connection generation allocation has started",
    ):
        alembic_runner.migrate_down_to(_FOUNDATION_REVISION)


def test_activation_downgrade_rejects_accepted_existing_subject_allocation(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Rollback rejects accepted allocation above an existing subject's seed."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_existing_subjects(connection)
    alembic_runner.migrate_up_to(_ACTIVATION_REVISION)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                UPDATE runtime_connection_generations
                SET high_water_generation = :generation,
                    accepted_generation = :generation
                WHERE connection_kind = 'provider'
                  AND subject_id = 'generation-provider'
                """
            ),
            {"generation": _LEGACY_CUTOVER_HIGH_WATER + 1},
        )

    with pytest.raises(
        RuntimeError,
        match="Runtime connection generation allocation has started",
    ):
        alembic_runner.migrate_down_to(_FOUNDATION_REVISION)
