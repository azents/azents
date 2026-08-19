"""Migration tests for the Session applied/prepared inference split."""

import pytest
import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

_PARENT_REVISION = "c05f9971773f"
_REVISION = "936373d16d53"


def _seed_base_rows(connection: sa.Connection) -> None:
    """Seed the minimum Workspace, Agent, and Session rows."""
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('session-profile-workspace', 'Session Profile', 'session-profile')
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
                'session-profile-agent', 'session-profile-workspace',
                'Session Profile Agent', '{}'::jsonb, '{}'::jsonb,
                '[{"label":"default","model_selection":{}}]'::jsonb,
                'default', 'default'
            )
            """
        )
    )


def test_applied_profile_backfills_complete_prepared_state_and_preserves_null(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Complete prepared state is copied while all-null state remains inherited."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_base_rows(connection)
        connection.execute(
            sa.text(
                """
                INSERT INTO agent_sessions (
                    id, workspace_id, agent_id, handle, status, start_reason,
                    session_kind, product_mode, run_state, current_model_target_label,
                    current_model_selection, current_model_settings,
                    current_reasoning_effort,
                    current_effective_context_window_tokens,
                    current_effective_auto_compaction_threshold_tokens,
                    current_inference_resolved_at
                )
                VALUES (
                    'session-profile-complete', 'session-profile-workspace',
                    'session-profile-agent', 'session-profile-complete',
                    'active', 'initial', 'root', 'team', 'idle', 'default',
                    '{}'::jsonb, '{}'::jsonb, 'high', 1000, 500,
                    NOW()
                ),
                (
                    'session-profile-null', 'session-profile-workspace',
                    'session-profile-agent', 'session-profile-null',
                    'active', 'initial', 'root', 'team', 'idle', NULL,
                    NULL, NULL, NULL, NULL, NULL, NULL
                )
                """
            )
        )

    alembic_runner.migrate_up_to(_REVISION)

    with alembic_engine.connect() as connection:
        rows = {
            row["id"]: row
            for row in connection.execute(
                sa.text(
                    """
                    SELECT id, applied_model_target_label, applied_reasoning_effort,
                           current_model_target_label, current_model_selection,
                           current_model_settings, current_reasoning_effort,
                           current_effective_context_window_tokens,
                           current_effective_auto_compaction_threshold_tokens,
                           current_inference_resolved_at
                    FROM agent_sessions
                    ORDER BY id
                    """
                )
            ).mappings()
        }
        assert (
            rows["session-profile-complete"]["applied_model_target_label"] == "default"
        )
        assert rows["session-profile-complete"]["applied_reasoning_effort"] == "high"
        assert (
            rows["session-profile-complete"]["current_model_target_label"] == "default"
        )
        assert rows["session-profile-complete"]["current_model_selection"] == {}
        assert rows["session-profile-complete"]["current_model_settings"] == {}
        assert rows["session-profile-complete"]["current_reasoning_effort"] == "high"
        assert (
            rows["session-profile-complete"]["current_effective_context_window_tokens"]
            == 1000
        )
        assert (
            rows["session-profile-complete"][
                "current_effective_auto_compaction_threshold_tokens"
            ]
            == 500
        )
        assert (
            rows["session-profile-complete"]["current_inference_resolved_at"]
            is not None
        )
        assert rows["session-profile-null"]["applied_model_target_label"] is None
        assert rows["session-profile-null"]["applied_reasoning_effort"] is None
        assert rows["session-profile-null"]["current_model_target_label"] is None
        assert rows["session-profile-null"]["current_model_selection"] is None
        assert rows["session-profile-null"]["current_model_settings"] is None
        assert rows["session-profile-null"]["current_reasoning_effort"] is None

        with pytest.raises(IntegrityError):
            connection.execute(
                sa.text(
                    """
                    UPDATE agent_sessions
                    SET applied_model_target_label = NULL,
                        applied_reasoning_effort = 'high'
                    WHERE id = 'session-profile-null'
                    """
                )
            )


def test_applied_profile_migration_fails_closed_on_partial_prepared_state(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """The forward migration rejects partial legacy prepared state."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_base_rows(connection)
        connection.execute(
            sa.text(
                "ALTER TABLE agent_sessions "
                "DROP CONSTRAINT ck_agent_sessions_current_inference_state"
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO agent_sessions (
                    id, workspace_id, agent_id, handle, status, start_reason,
                    session_kind, product_mode, run_state,
                    current_model_target_label, current_model_selection,
                    current_model_settings, current_reasoning_effort
                )
                VALUES (
                    'session-profile-partial', 'session-profile-workspace',
                    'session-profile-agent', 'session-profile-partial',
                    'active', 'initial', 'root', 'team', 'idle', 'default',
                    NULL, NULL, NULL
                ),
                (
                    'session-profile-partial-effort', 'session-profile-workspace',
                    'session-profile-agent', 'session-profile-partial-effort',
                    'active', 'initial', 'root', 'team', 'idle', NULL,
                    NULL, NULL, 'high'
                )
                """
            )
        )

    with pytest.raises(DBAPIError, match="partial current inference state"):
        alembic_runner.migrate_up_to(_REVISION)
