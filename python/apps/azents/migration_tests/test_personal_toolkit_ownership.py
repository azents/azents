"""Preserving forward ownership migration and guarded rollback."""

import pytest
import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT = "f79f6654c302"
_REVISION = "716e7468e1f5"
_STORED_CONFIGURATION = sa.text(
    "SELECT id, workspace_id, owner_agent_id, config, encrypted_credentials, "
    "revision FROM toolkit_configs ORDER BY id"
)


def seed_shared(engine: Engine, *, inconsistent: bool) -> None:
    """Seed the immediate predecessor with canonical IDs and opaque credentials."""
    with engine.begin() as connection:
        connection.execute(
            sa.text("""
            INSERT INTO workspaces (id, name, handle) VALUES
                ('personal-w1', 'One', 'personal-one'),
                ('personal-w2', 'Two', 'personal-two')
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO agents (
                id, workspace_id, name, model_selection,
                lightweight_model_selection, selectable_model_options,
                main_model_label, lightweight_model_label, enabled, type,
                memory_enabled
            ) VALUES (
                'personal-agent', 'personal-w1', 'Agent', '{}'::jsonb,
                '{}'::jsonb,
                '[{"label":"default","candidates":[{"model_selection":{}}]}]'::jsonb,
                'default', 'default', TRUE, 'public', TRUE
            )
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO toolkit_configs (
                id, workspace_id, owner_agent_id, toolkit_type, slug, name,
                config, encrypted_credentials, revision, enabled
            ) VALUES
                ('personal-shared', 'personal-w1', NULL, 'mcp', 'shared', 'Shared',
                 '{"server_url":"https://example.test"}'::jsonb,
                 'opaque-shared', 7, TRUE),
                ('personal-owned', :workspace, 'personal-agent', 'mcp', 'owned',
                 'Owned', '{}'::jsonb, 'opaque-owned', 9, TRUE)
        """),
            {"workspace": "personal-w2" if inconsistent else "personal-w1"},
        )


def test_forward_preserves_existing_canonical_identity_and_configuration(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Existing Workspace/Agent records get no personal policy or owner."""
    alembic_runner.migrate_up_to(_PARENT)
    seed_shared(alembic_engine, inconsistent=False)
    with alembic_engine.connect() as connection:
        before = connection.execute(_STORED_CONFIGURATION).all()
    alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.connect() as connection:
        assert connection.execute(_STORED_CONFIGURATION).all() == before
        assert connection.execute(
            sa.text("SELECT id, owner_kind FROM toolkit_configs ORDER BY id")
        ).all() == [("personal-owned", "agent"), ("personal-shared", "workspace")]
        assert connection.execute(
            sa.text("SELECT owner_user_id, personal_access_mode FROM toolkit_configs")
        ).all() == [(None, None), (None, None)]
    alembic_runner.migrate_down_to(_PARENT)
    with alembic_engine.connect() as connection:
        assert connection.execute(_STORED_CONFIGURATION).all() == before


def test_forward_rejects_inconsistent_existing_owner(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """An Agent/Workspace mismatch fails before any ownership conversion."""
    alembic_runner.migrate_up_to(_PARENT)
    seed_shared(alembic_engine, inconsistent=True)
    with pytest.raises(RuntimeError, match="Inconsistent Toolkit ownership"):
        alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
            == _PARENT
        )
        assert (
            connection.scalar(sa.text("SELECT to_regclass('personal_toolkit_agents')"))
            is None
        )


def test_downgrade_refuses_to_discard_user_owned_data(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Rollback refuses to discard personal connections for Workspace-only storage."""
    alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text("""
            INSERT INTO users (id, primary_email_id)
            VALUES ('personal-user', 'personal-email')
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO user_emails (id, user_id, email)
            VALUES ('personal-email', 'personal-user', 'personal@example.test')
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO toolkit_configs (
                id, owner_user_id, personal_access_mode, owner_kind,
                toolkit_type, slug, name, config, enabled
            ) VALUES (
                'personal-toolkit', 'personal-user', 'all', 'user',
                'mcp', 'personal', 'Personal', '{}'::jsonb, TRUE
            )
        """)
        )
    with pytest.raises(RuntimeError, match="Cannot discard personal Toolkits"):
        alembic_runner.migrate_down_to(_PARENT)
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
            == _REVISION
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT owner_user_id FROM toolkit_configs "
                    "WHERE id = 'personal-toolkit'"
                )
            )
            == "personal-user"
        )
