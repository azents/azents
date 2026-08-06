"""Migration tests for AgentSession product mode and associated user."""

import pytest
import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

_PARENT_REVISION = "d51acb332a07"
_REVISION = "2a9ad984951f"


def _seed_sessions(connection: sa.Connection) -> None:
    """Seed one root and one subagent session before the product-mode cutover."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('product-mode-workspace', 'Product Mode', 'product-mode')
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
                'product-mode-agent', 'product-mode-workspace', 'Product Mode Agent',
                '{}'::jsonb, '{}'::jsonb,
                '[
                    {"label": "product-mode-main", "model_selection": {}},
                    {"label": "product-mode-light", "model_selection": {}}
                ]'::jsonb,
                'product-mode-main', 'product-mode-light'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status, start_reason,
                session_kind, run_state, primary_kind
            )
            VALUES
            (
                'product-mode-root', 'product-mode-workspace', 'product-mode-agent',
                'product-mode-root', 'active', 'initial', 'root', 'idle',
                'team_primary'
            ),
            (
                'product-mode-child', 'product-mode-workspace', 'product-mode-agent',
                'product-mode-child', 'active', 'initial', 'subagent', 'idle',
                NULL
            )
            """
        )
    )


def test_product_mode_backfill_and_constraints(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Existing roots become Team mode and invalid combinations are rejected."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_sessions(connection)

    alembic_runner.migrate_up_to(_REVISION)

    with alembic_engine.connect() as connection:
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, session_kind, product_mode, associated_user_id,
                           primary_kind
                    FROM agent_sessions
                    ORDER BY id
                    """
                )
            )
            .mappings()
            .all()
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id["product-mode-root"]["product_mode"] == "team"
        assert by_id["product-mode-root"]["associated_user_id"] is None
        assert by_id["product-mode-root"]["primary_kind"] == "team_primary"
        assert by_id["product-mode-child"]["product_mode"] is None
        assert by_id["product-mode-child"]["associated_user_id"] is None

        enum_names = set(
            connection.scalars(
                sa.text(
                    """
                    SELECT typname
                    FROM pg_type
                    WHERE typtype = 'e'
                      AND typnamespace = to_regnamespace('public')
                    """
                )
            )
        )
        assert "agent_session_product_mode" in enum_names

    with pytest.raises(IntegrityError):
        with alembic_engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO agent_sessions (
                        id, workspace_id, agent_id, handle, status, start_reason,
                        session_kind, run_state, product_mode, associated_user_id
                    )
                    VALUES (
                        'invalid-user-root', 'product-mode-workspace',
                        'product-mode-agent', 'invalid-user-root', 'active',
                        'initial', 'root', 'idle', 'user', NULL
                    )
                    """
                )
            )
