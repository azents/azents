"""Migration tests for optional managed Runtime persistence."""

import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT_REVISION = "346454f625fe"
_REVISION = "4c64a691eddc"


def _seed_existing_runtime_state(connection: sa.Connection) -> None:
    """Seed one existing Agent, Runtime, and Session context."""
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES (
                'optional-runtime-workspace',
                'Optional Runtime',
                'optional-runtime'
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
            )
            VALUES (
                'optional-runtime-agent',
                'optional-runtime-workspace',
                'Optional Runtime Agent',
                '{}'::jsonb,
                '{}'::jsonb,
                '[
                    {"label": "default", "model_selection": {}}
                ]'::jsonb,
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
                id, workspace_id, agent_id, desired_generation,
                terminal_delete_requested_generation,
                terminal_delete_acknowledged_generation,
                terminal_delete_acknowledged_at
            )
            VALUES (
                'optional-runtime-logical',
                'optional-runtime-workspace',
                'optional-runtime-agent',
                1,
                1,
                1,
                now()
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO session_agent_contexts (
                id, agent_id, workspace_id, agent_runtime_id,
                working_folder_path, working_folder_cleanup_status,
                working_folder_cleanup_summary,
                working_folder_cleanup_completed_at
            )
            VALUES (
                'optional-runtime-context',
                'optional-runtime-agent',
                'optional-runtime-workspace',
                'optional-runtime-logical',
                '/runtime/optional/.azents/sessions/existing',
                'failed',
                'historical cleanup result',
                now()
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO session_agent_contexts (
                id, agent_id, workspace_id, agent_runtime_id,
                working_folder_path, working_folder_cleanup_status,
                working_folder_cleanup_summary,
                working_folder_cleanup_completed_at
            )
            VALUES (
                'optional-runtime-legacy-context',
                'optional-runtime-agent',
                'optional-runtime-workspace',
                NULL,
                '/runtime/optional/.azents/sessions/legacy',
                'not_attempted',
                NULL,
                NULL
            )
            """
        )
    )


def test_existing_state_backfills_without_runtime_side_effects(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Existing Agents and contexts retain managed Runtime authority."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_existing_runtime_state(connection)

    alembic_runner.migrate_up_to(_REVISION)

    with alembic_engine.connect() as connection:
        agent = (
            connection.execute(
                sa.text(
                    """
                    SELECT runtime_capability, runtime_capability_version,
                           runtime_profile_id, shell_enabled
                    FROM agents
                    WHERE id = 'optional-runtime-agent'
                    """
                )
            )
            .mappings()
            .one()
        )
        assert agent["runtime_capability"] == "managed"
        assert agent["runtime_capability_version"] == 1
        assert agent["runtime_profile_id"] is None
        assert agent["shell_enabled"] is True

        runtime = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, terminal_delete_acknowledgement_kind
                    FROM agent_runtimes
                    WHERE agent_id = 'optional-runtime-agent'
                    """
                )
            )
            .mappings()
            .one()
        )
        assert runtime["id"] == "optional-runtime-logical"
        assert runtime["terminal_delete_acknowledgement_kind"] == "provider_report"

        context = (
            connection.execute(
                sa.text(
                    """
                    SELECT agent_runtime_id, working_folder_path,
                           working_folder_binding_state,
                           working_folder_cleanup_status,
                           working_folder_cleanup_summary
                    FROM session_agent_contexts
                    WHERE id = 'optional-runtime-context'
                    """
                )
            )
            .mappings()
            .one()
        )
        assert context["agent_runtime_id"] == "optional-runtime-logical"
        assert context["working_folder_path"] == (
            "/runtime/optional/.azents/sessions/existing"
        )
        assert context["working_folder_binding_state"] == "bound"
        assert context["working_folder_cleanup_status"] == "failed"
        assert context["working_folder_cleanup_summary"] == (
            "historical cleanup result"
        )

        legacy_context = (
            connection.execute(
                sa.text(
                    """
                    SELECT agent_runtime_id, working_folder_path,
                           working_folder_binding_state,
                           working_folder_cleanup_status
                    FROM session_agent_contexts
                    WHERE id = 'optional-runtime-legacy-context'
                    """
                )
            )
            .mappings()
            .one()
        )
        assert legacy_context["agent_runtime_id"] == "optional-runtime-logical"
        assert legacy_context["working_folder_path"] == (
            "/runtime/optional/.azents/sessions/legacy"
        )
        assert legacy_context["working_folder_binding_state"] == "bound"
        assert legacy_context["working_folder_cleanup_status"] == "not_attempted"

        runtime_count = connection.scalar(
            sa.text(
                """
                SELECT count(*)
                FROM agent_runtimes
                WHERE agent_id = 'optional-runtime-agent'
                """
            )
        )
        operation_count = connection.scalar(
            sa.text("SELECT count(*) FROM agent_runtime_removal_operations")
        )
        assert runtime_count == 1
        assert operation_count == 0


def test_runtime_free_context_shape_and_downgrade(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """The additive schema permits an explicitly unbound context."""
    alembic_runner.migrate_up_to(_REVISION)

    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO workspaces (id, name, handle)
                VALUES ('runtime-free-workspace', 'Runtime Free', 'runtime-free')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO agents (
                    id, workspace_id, name, model_selection,
                    lightweight_model_selection, selectable_model_options,
                    main_model_label, lightweight_model_label,
                    runtime_capability, shell_enabled
                )
                VALUES (
                    'runtime-free-agent',
                    'runtime-free-workspace',
                    'Runtime Free Agent',
                    '{}'::jsonb,
                    '{}'::jsonb,
                    '[{"label": "default", "model_selection": {}}]'::jsonb,
                    'default',
                    'default',
                    'none',
                    false
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO session_agent_contexts (
                    id, agent_id, workspace_id, agent_runtime_id,
                    working_folder_path, working_folder_binding_state,
                    working_folder_cleanup_status,
                    working_folder_cleanup_summary,
                    working_folder_cleanup_completed_at
                )
                VALUES (
                    'runtime-free-context',
                    'runtime-free-agent',
                    'runtime-free-workspace',
                    NULL,
                    NULL,
                    'none',
                    'not_attempted',
                    NULL,
                    NULL
                )
                """
            )
        )

    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                DELETE FROM session_agent_contexts
                WHERE id = 'runtime-free-context'
                """
            )
        )
        connection.execute(
            sa.text("DELETE FROM agents WHERE id = 'runtime-free-agent'")
        )
        connection.execute(
            sa.text("DELETE FROM workspaces WHERE id = 'runtime-free-workspace'")
        )

    alembic_runner.migrate_down_to(_PARENT_REVISION)
