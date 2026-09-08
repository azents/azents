"""Migration tests for durable Runtime connection-generation authority."""

import pytest
import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT_REVISION = "4ab7015e39b5"
_REVISION = "fa67b82b0b53"


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

    alembic_runner.migrate_up_to(_REVISION)

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
    alembic_runner.migrate_up_to(_REVISION)
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
    alembic_runner.migrate_up_to(_REVISION)
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
