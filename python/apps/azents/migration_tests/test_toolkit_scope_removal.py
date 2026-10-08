"""Isolated migration evidence for deleting only obsolete Toolkit visibility state."""

import pytest
import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

_PARENT = "95521a5a1bbc"
_REVISION = "7b6d0eb501fb"
_RESOURCE_TABLES = (
    "workspaces",
    "agents",
    "toolkit_configs",
    "agent_toolkits",
    "agent_toolkit_namespace_reservations",
    "agent_toolkit_namespace_sequences",
    "mcp_oauth_connections",
)


def _seed_legacy_visibility_resources(engine: Engine) -> None:
    """Seed old-schema resources only inside the dedicated migration-test database."""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO workspaces (id, name, handle) "
                "VALUES ('scope-workspace', 'Scope removal', 'scope-removal')"
            )
        )
        connection.execute(
            sa.text("""
            INSERT INTO agents (
                id, workspace_id, name, model_selection,
                lightweight_model_selection, selectable_model_options,
                main_model_label, lightweight_model_label, enabled, type,
                memory_enabled
            ) VALUES (
                'scope-agent', 'scope-workspace', 'Scope Agent',
                '{}'::jsonb, '{}'::jsonb,
                '[{"label":"default","candidates":[{"model_selection":{}}]}]'::jsonb,
                'default', 'default', TRUE, 'public', TRUE
            )
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO toolkit_configs (
                id, workspace_id, owner_agent_id, toolkit_type, slug, name,
                config, encrypted_credentials, enabled, always_expose_tools,
                revision
            ) VALUES
                ('scope-shared', 'scope-workspace', NULL, 'mcp', 'duplicate',
                 'Shared', '{"scopes":["read:resources"]}'::jsonb,
                 'opaque-credential-shared', TRUE, FALSE, 3),
                ('scope-hidden', 'scope-workspace', NULL, 'mcp', 'duplicate',
                 'Formerly hidden', '{}'::jsonb,
                 'opaque-credential-hidden', TRUE, FALSE, 4),
                ('scope-disabled', 'scope-workspace', NULL, 'mcp', 'disabled',
                 'Disabled', '{}'::jsonb, NULL, FALSE, TRUE, 2),
                ('scope-owned', 'scope-workspace', 'scope-agent', 'mcp', 'owned',
                 'Agent only', '{}'::jsonb,
                 'opaque-credential-owned', TRUE, FALSE, 5)
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO toolkit_scopes (id, toolkit_id, scope_type, scope_id)
            VALUES ('scope-row', 'scope-shared', 'workspace', 'scope-workspace')
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO agent_toolkits (id, agent_id, toolkit_id, toolkit_type)
            VALUES
                ('scope-attachment-shared', 'scope-agent', 'scope-shared', 'mcp'),
                ('scope-attachment-hidden', 'scope-agent', 'scope-hidden', 'mcp')
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO agent_toolkit_namespace_reservations (
                id, agent_id, toolkit_id, base_slug, ordinal, namespace
            ) VALUES
                ('scope-reservation-shared', 'scope-agent', 'scope-shared',
                 'duplicate', 1, 'duplicate'),
                ('scope-reservation-hidden', 'scope-agent', 'scope-hidden',
                 'duplicate', 2, 'duplicate_2'),
                ('scope-reservation-owned', 'scope-agent', 'scope-owned',
                 'owned', 1, 'owned')
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO agent_toolkit_namespace_sequences (
                id, agent_id, base_slug, last_ordinal
            ) VALUES
                ('scope-sequence-shared', 'scope-agent', 'duplicate', 2),
                ('scope-sequence-owned', 'scope-agent', 'owned', 1)
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO mcp_oauth_connections (
                id, toolkit_id, server_url, authorization_endpoint,
                token_endpoint, encrypted_client_id, token_endpoint_auth_method,
                encrypted_client_secret, encrypted_access_token,
                encrypted_refresh_token, scope, status
            ) VALUES (
                'scope-oauth', 'scope-shared', 'https://mcp.example.test',
                'https://mcp.example.test/authorize',
                'https://mcp.example.test/token', 'opaque-client-id',
                'client_secret_post', 'opaque-client-secret',
                'opaque-access-token', 'opaque-refresh-token',
                'read:resources', 'connected'
            )
        """)
        )


def test_visibility_removal_preserves_all_toolkit_resources(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Drop scope state while retaining exact configs, secrets, grants and bindings."""
    alembic_runner.migrate_up_to(_PARENT)
    _seed_legacy_visibility_resources(alembic_engine)
    with alembic_engine.connect() as connection:
        before = {
            table: connection.execute(
                sa.text(f"SELECT * FROM {table} ORDER BY id")
            ).all()
            for table in _RESOURCE_TABLES
        }
        incoming = connection.execute(
            sa.text(
                "SELECT conname FROM pg_constraint "
                "WHERE contype = 'f' AND confrelid = 'toolkit_scopes'::regclass"
            )
        ).all()
        assert incoming == []
    alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.connect() as connection:
        for table in _RESOURCE_TABLES:
            after = connection.execute(
                sa.text(f"SELECT * FROM {table} ORDER BY id")
            ).all()
            assert after == before[table], table
        assert (
            connection.scalar(sa.text("SELECT to_regclass('toolkit_scopes')")) is None
        )
        assert (
            connection.scalar(sa.text("SELECT to_regtype('toolkit_scope_type')"))
            is None
        )
        eligible = (
            connection.execute(
                sa.text(
                    "SELECT id FROM toolkit_configs "
                    "WHERE workspace_id = 'scope-workspace' AND owner_agent_id IS NULL "
                    "AND enabled ORDER BY id"
                )
            )
            .scalars()
            .all()
        )
        assert eligible == ["scope-hidden", "scope-shared"]
        assert (
            connection.scalar(
                sa.text(
                    "SELECT scope FROM mcp_oauth_connections WHERE id = 'scope-oauth'"
                )
            )
            == "read:resources"
        )


def test_visibility_removal_downgrade_does_not_invent_assignments(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Reject a false historical reconstruction and retain the migrated revision."""
    alembic_runner.migrate_up_to(_REVISION)
    with pytest.raises(RuntimeError, match="visibility scope removal is irreversible"):
        alembic_runner.migrate_down_to(_PARENT)
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
            == _REVISION
        )
        assert (
            connection.scalar(sa.text("SELECT to_regclass('toolkit_scopes')")) is None
        )


def test_visibility_removal_rejects_unexpected_dependencies(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Refuse broad CASCADE removal when an unexpected dependent object exists."""
    alembic_runner.migrate_up_to(_PARENT)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE VIEW retained_visibility_reference "
                "AS SELECT toolkit_id FROM toolkit_scopes"
            )
        )
    with pytest.raises(DBAPIError, match="other objects depend on it"):
        alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
            == _PARENT
        )
        assert (
            connection.scalar(sa.text("SELECT to_regclass('toolkit_scopes')"))
            is not None
        )
        assert (
            connection.scalar(sa.text("SELECT to_regtype('toolkit_scope_type')"))
            is not None
        )
        assert (
            connection.scalar(
                sa.text("SELECT to_regclass('retained_visibility_reference')")
            )
            is not None
        )
