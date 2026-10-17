"""Preserve pending Provider setup when introducing explicit personal targets."""

import pytest
import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT = "716e7468e1f5"
_REVISION = "004bda2b6938"


def seed_google_attempts(engine: Engine) -> None:
    """Seed predecessor shared/Agent attempts with opaque setup bytes."""
    with engine.begin() as connection:
        connection.execute(
            sa.text("""
            INSERT INTO workspaces (id, name, handle)
            VALUES ('provider-workspace', 'Provider targets', 'provider-targets')
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO agents (
                id, workspace_id, name, model_selection, lightweight_model_selection,
                selectable_model_options, main_model_label, lightweight_model_label,
                enabled, type, memory_enabled
            ) VALUES (
                'provider-agent', 'provider-workspace', 'Agent',
                '{}'::jsonb, '{}'::jsonb,
                '[{"label":"default","candidates":[{"model_selection":{}}]}]'::jsonb,
                'default', 'default', TRUE, 'public', TRUE
            )
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO google_oauth_attempts (
                id, user_id, session_id, workspace_id, agent_id, status,
                expires_at, encrypted_setup, encrypted_candidate
            ) VALUES
                ('provider-shared', 'manager', 'login', 'provider-workspace', NULL,
                 'pending', now() + interval '10 minutes', 'opaque-shared', NULL),
                ('provider-owned', 'manager', 'login', 'provider-workspace',
                 'provider-agent', 'review', now() + interval '10 minutes',
                 'opaque-owned', 'opaque-candidate')
        """)
        )


def test_attempt_classification_preserves_shared_pending_payloads(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Existing staged attempts keep their context and ciphertext."""
    alembic_runner.migrate_up_to(_PARENT)
    seed_google_attempts(alembic_engine)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text("""
            INSERT INTO toolkit_configs (
                id, workspace_id, owner_agent_id, owner_kind,
                toolkit_type, slug, name, config, enabled
            ) VALUES
                ('provider-gh-shared', 'provider-workspace', NULL, 'workspace',
                 'github', 'shared', 'Shared', '{}'::jsonb, TRUE),
                ('provider-gh-owned', 'provider-workspace', 'provider-agent', 'agent',
                 'github', 'owned', 'Owned', '{}'::jsonb, TRUE)
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO github_user_oauth_attempts (
                id, toolkit_id, user_id, session_id, workspace_id, agent_id,
                encrypted_setup, encrypted_candidate, status, expires_at
            ) VALUES
                ('provider-gh-a-shared', 'provider-gh-shared', 'manager', 'login',
                 'provider-workspace', NULL, 'opaque-github-shared', NULL,
                 'pending', now() + interval '10 minutes'),
                ('provider-gh-a-owned', 'provider-gh-owned', 'manager', 'login',
                 'provider-workspace', 'provider-agent', 'opaque-github-owned',
                 'opaque-github-candidate', 'review', now() + interval '10 minutes')
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO github_user_oauth_creations (
                id, user_id, session_id, workspace_id, agent_id,
                encrypted_setup, encrypted_candidate, status, expires_at
            ) VALUES
                ('provider-gh-c-shared', 'manager', 'login', 'provider-workspace',
                 NULL, 'opaque-github-create-shared', NULL, 'pending',
                 now() + interval '10 minutes'),
                ('provider-gh-c-owned', 'manager', 'login', 'provider-workspace',
                 'provider-agent', 'opaque-github-create-owned',
                 'opaque-github-create-candidate', 'review',
                 now() + interval '10 minutes')
        """)
        )
    original = sa.text(
        "SELECT id, user_id, session_id, workspace_id, agent_id, status, expires_at, "
        "encrypted_setup, encrypted_candidate FROM google_oauth_attempts ORDER BY id"
    )
    with alembic_engine.connect() as connection:
        before = connection.execute(original).all()
        github_before = {
            table: connection.execute(
                sa.text(
                    "SELECT id, user_id, session_id, workspace_id, agent_id, "
                    "encrypted_setup, encrypted_candidate, status, expires_at "
                    f"FROM {table} ORDER BY id"
                )
            ).all()
            for table in ("github_user_oauth_attempts", "github_user_oauth_creations")
        }
    alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.connect() as connection:
        assert connection.execute(original).all() == before
        assert connection.execute(
            sa.text(
                "SELECT owner_kind, owner_user_id FROM google_oauth_attempts "
                "ORDER BY id"
            )
        ).all() == [("agent", None), ("workspace", None)]
        for table, expected in github_before.items():
            assert (
                connection.execute(
                    sa.text(
                        "SELECT id, user_id, session_id, workspace_id, agent_id, "
                        "encrypted_setup, encrypted_candidate, status, expires_at "
                        f"FROM {table} ORDER BY id"
                    )
                ).all()
                == expected
            )
            assert connection.execute(
                sa.text(f"SELECT owner_kind, owner_user_id FROM {table} ORDER BY id")
            ).all() == [("agent", None), ("workspace", None)]
    alembic_runner.migrate_down_to(_PARENT)
    with alembic_engine.connect() as connection:
        assert connection.execute(original).all() == before


def test_personal_provider_attempt_blocks_destructive_downgrade(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Rollback retains personal staged credentials for explicit operator handling."""
    alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO workspaces (id, name, handle) "
                "VALUES ('provider-workspace', 'Provider', 'provider-personal')"
            )
        )
        connection.execute(
            sa.text("""
            INSERT INTO users (id, primary_email_id)
            VALUES ('provider-user', 'provider-email')
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO user_emails (id, user_id, email)
            VALUES ('provider-email', 'provider-user', 'provider@example.test')
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO google_oauth_attempts (
                id, workspace_id, user_id, session_id, owner_kind, owner_user_id,
                status, expires_at, encrypted_setup
            ) VALUES (
                'provider-personal', 'provider-workspace', 'provider-user', 'login',
                'user', 'provider-user',
                'pending', now() + interval '10 minutes', 'opaque-personal-setup'
            )
        """)
        )
    with pytest.raises(RuntimeError, match="Cannot discard personal Provider setup"):
        alembic_runner.migrate_down_to(_PARENT)
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
            == _REVISION
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT encrypted_setup FROM google_oauth_attempts "
                    "WHERE id = 'provider-personal'"
                )
            )
            == "opaque-personal-setup"
        )
