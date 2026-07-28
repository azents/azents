"""Migration integration tests for External Channel App mode foundation."""

from collections.abc import Generator

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "b6088a911203"
_REVISION = "00ae8d1fd42c"


def _database() -> Generator[tuple[AlembicConfig, sa.Engine], None, None]:
    """Create one isolated PostgreSQL database for migration integration tests."""
    with PostgresContainer("postgres:17", driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        engine = sa.create_engine(url)
        try:
            yield config, engine
        finally:
            engine.dispose()


def _seed_identity_graph(connection: sa.Connection) -> None:
    """Seed FK-valid tenant, user, Agent, Session, and connection roots."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO users (id, primary_email_id)
            VALUES ('u', 'email-u')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO user_emails (id, user_id, email, verified_at)
            VALUES ('email-u', 'u', 'migration@example.com', now())
            """
        )
    )
    connection.execute(
        sa.text("INSERT INTO workspaces (id, name, handle) VALUES ('w', 'W', 'w')")
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO workspace_users (id, workspace_id, user_id, name, role)
            VALUES ('wu', 'w', 'u', 'Migration User', 'owner')
            """
        )
    )
    _insert_agent(connection, agent_id="a", workspace_id="w")
    _insert_session(connection, session_id="s", workspace_id="w", agent_id="a")
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_connections (
                id, workspace_id, provider, transport, status, provider_app_id,
                provider_tenant_id, encrypted_credentials
            )
            VALUES ('c', 'w', 'slack', 'http', 'active', 'A1', 'T1',
                    'migration-ciphertext-sentinel')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_principals (
                id, provider, provider_tenant_id, provider_user_id, author_type
            )
            VALUES ('p', 'slack', 'T1', 'U1', 'human')
            """
        )
    )


def _insert_agent(
    connection: sa.Connection,
    *,
    agent_id: str,
    workspace_id: str,
) -> None:
    """Insert one parent-revision Agent with valid model metadata."""
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id, workspace_id, name, model_selection, lightweight_model_selection,
                selectable_model_options, main_model_label, lightweight_model_label
            )
            VALUES (
                :agent_id, :workspace_id, :agent_id, '{}'::jsonb, '{}'::jsonb,
                '[
                    {"label": "migration-main", "model_selection": {}},
                    {"label": "migration-lightweight", "model_selection": {}}
                ]'::jsonb,
                'migration-main', 'migration-lightweight'
            )
            """
        ),
        {"agent_id": agent_id, "workspace_id": workspace_id},
    )


def _insert_session(
    connection: sa.Connection,
    *,
    session_id: str,
    workspace_id: str,
    agent_id: str,
) -> None:
    """Insert one valid external-channel Session for a legacy binding."""
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status, start_reason, session_kind
            )
            VALUES (:session_id, :workspace_id, :agent_id, :session_id, 'active',
                    'external_channel', 'root')
            """
        ),
        {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
        },
    )


def _insert_route(
    connection: sa.Connection,
    *,
    route_id: str,
    agent_id: str,
    route_mode: str = "dedicated",
) -> None:
    """Insert one legacy route while retaining the parent route-mode behavior."""
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_agent_routes (
                id, connection_id, agent_id, route_mode
            )
            VALUES (:route_id, 'c', :agent_id, :route_mode)
            """
        ),
        {"route_id": route_id, "agent_id": agent_id, "route_mode": route_mode},
    )


def _insert_resource_history_and_binding(connection: sa.Connection) -> None:
    """Seed retained legacy state whose IDs and references must remain unchanged."""
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_resources (
                id, connection_id, resource_type, provider_resource_key, status
            )
            VALUES ('resource', 'c', 'thread', 'slack:T1:C1:1.000001', 'active')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_messages (
                id, resource_id, provider_message_key, provider_position, lifecycle,
                author_type, principal_id
            )
            VALUES ('message', 'resource', 'slack:T1:C1:1.000001', '1.000001',
                    'current', 'human', 'p')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_message_revisions (
                id, message_id, revision_key, revision_kind, normalized_body,
                attachment_metadata
            )
            VALUES ('revision', 'message', 'v1', 'original', 'legacy request',
                    '{"attachment_count": 1}'::jsonb)
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE external_channel_messages
            SET current_revision_id = 'revision'
            WHERE id = 'message'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_pending_contexts (
                id, route_id, resource_id, message_revision_id, provider_position,
                normalized_size, expires_at
            )
            VALUES ('pending', 'route', 'resource', 'revision', '1.000001', 14,
                    now() + interval '1 day')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_access_requests (
                id, route_id, resource_id, source_message_id, principal_id, status,
                decision_policy_snapshot, expires_at
            )
            VALUES ('access', 'route', 'resource', 'message', 'p', 'pending',
                    '{"policy": "legacy"}'::jsonb, now() + interval '1 day')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_bindings (
                id, resource_id, route_id, agent_session_id, status
            )
            VALUES ('binding', 'resource', 'route', 's', 'active')
            """
        )
    )


def _seed_valid_parent_graph(connection: sa.Connection) -> None:
    """Seed the exact parent graph used for identity-preservation assertions."""
    _seed_identity_graph(connection)
    _insert_route(connection, route_id="route", agent_id="a")
    _insert_resource_history_and_binding(connection)


def _snapshot(connection: sa.Connection) -> dict[str, object]:
    """Capture every retained Phase 1 legacy identity and critical reference."""
    return {
        "user": connection.execute(
            sa.text(
                """
                SELECT id, primary_email_id FROM users WHERE id = 'u'
                """
            )
        )
        .mappings()
        .one(),
        "user_email": connection.execute(
            sa.text(
                """
                SELECT id, user_id, email, verified_at
                FROM user_emails WHERE id = 'email-u'
                """
            )
        )
        .mappings()
        .one(),
        "workspace": connection.execute(
            sa.text(
                """
                SELECT id, name, handle FROM workspaces WHERE id = 'w'
                """
            )
        )
        .mappings()
        .one(),
        "workspace_user": connection.execute(
            sa.text(
                """
                SELECT id, workspace_id, user_id, name, role
                FROM workspace_users WHERE id = 'wu'
                """
            )
        )
        .mappings()
        .one(),
        "agent": connection.execute(
            sa.text(
                """
                SELECT id, workspace_id, lifecycle_status, model_selection,
                       lightweight_model_selection, main_model_label,
                       lightweight_model_label
                FROM agents WHERE id = 'a'
                """
            )
        )
        .mappings()
        .one(),
        "agent_session": connection.execute(
            sa.text(
                """
                SELECT id, workspace_id, agent_id, handle, status, start_reason,
                       session_kind
                FROM agent_sessions WHERE id = 's'
                """
            )
        )
        .mappings()
        .one(),
        "connection": connection.execute(
            sa.text(
                """
                SELECT id, workspace_id, provider, transport, status, provider_app_id,
                       provider_tenant_id, encrypted_credentials
                FROM external_channel_connections WHERE id = 'c'
                """
            )
        )
        .mappings()
        .one(),
        "principal": connection.execute(
            sa.text(
                """
                SELECT id, provider, provider_tenant_id, provider_user_id, author_type
                FROM external_channel_principals WHERE id = 'p'
                """
            )
        )
        .mappings()
        .one(),
        "route": connection.execute(
            sa.text(
                """
                SELECT id, connection_id, agent_id, route_mode
                FROM external_channel_agent_routes WHERE id = 'route'
                """
            )
        )
        .mappings()
        .one(),
        "resource": connection.execute(
            sa.text(
                "SELECT id, connection_id FROM external_channel_resources "
                "WHERE id = 'resource'"
            )
        )
        .mappings()
        .one(),
        "message": connection.execute(
            sa.text(
                """
                SELECT id, resource_id, current_revision_id
                FROM external_channel_messages WHERE id = 'message'
                """
            )
        )
        .mappings()
        .one(),
        "revision": connection.execute(
            sa.text(
                """
                SELECT id, message_id, attachment_metadata
                FROM external_channel_message_revisions WHERE id = 'revision'
                """
            )
        )
        .mappings()
        .one(),
        "pending": connection.execute(
            sa.text(
                """
                SELECT id, route_id, resource_id, message_revision_id
                FROM external_channel_pending_contexts WHERE id = 'pending'
                """
            )
        )
        .mappings()
        .one(),
        "access": connection.execute(
            sa.text(
                """
                SELECT id, route_id, resource_id, source_message_id, principal_id
                FROM external_channel_access_requests WHERE id = 'access'
                """
            )
        )
        .mappings()
        .one(),
        "binding": connection.execute(
            sa.text(
                """
                SELECT id, resource_id, route_id, agent_session_id, status
                FROM external_channel_bindings WHERE id = 'binding'
                """
            )
        )
        .mappings()
        .one(),
        "counts": tuple(
            connection.scalar(sa.text(f"SELECT count(*) FROM {table}"))
            for table in (
                "users",
                "user_emails",
                "workspaces",
                "workspace_users",
                "agents",
                "agent_sessions",
                "external_channel_connections",
                "external_channel_principals",
                "external_channel_agent_routes",
                "external_channel_resources",
                "external_channel_messages",
                "external_channel_message_revisions",
                "external_channel_pending_contexts",
                "external_channel_access_requests",
                "external_channel_bindings",
            )
        ),
    }


def _close(database: Generator[tuple[AlembicConfig, sa.Engine], None, None]) -> None:
    """Finish the isolated database generator even when an assertion fails."""
    try:
        next(database)
    except StopIteration:
        pass


def test_external_channel_app_mode_migration_preserves_legacy_identity_and_downgrades(
    check_docker_availability: None,
) -> None:
    """Upgrade and clean downgrade retain every pre-feature durable identity."""
    del check_docker_availability
    database = _database()
    config, engine = next(database)
    try:
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_valid_parent_graph(connection)
        with engine.connect() as connection:
            before = _snapshot(connection)

        alembic_command.upgrade(config, _REVISION)

        with engine.connect() as connection:
            assert _snapshot(connection) == before
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT app_mode FROM external_channel_connections "
                        "WHERE id = 'c'"
                    )
                )
                == "single"
            )
            assert connection.execute(
                sa.text(
                    """
                    SELECT connection_app_mode, catalog_status
                    FROM external_channel_agent_routes WHERE id = 'route'
                    """
                )
            ).one() == ("single", "available")
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM external_channel_connections "
                        "WHERE app_mode = 'multi'"
                    )
                )
                == 0
            )
            assert (
                connection.scalar(
                    sa.text("SELECT count(*) FROM external_channel_agent_routes")
                )
                == 1
            )

        with pytest.raises(DBAPIError, match="immutable"):
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE external_channel_connections SET app_mode = 'multi' "
                        "WHERE id = 'c'"
                    )
                )
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO external_channel_connections (
                        id, workspace_id, provider, transport, status, app_mode
                    )
                    VALUES ('multi-probe', 'w', 'slack', 'http', 'configuring', 'multi')
                    """
                )
            )
        with pytest.raises(DBAPIError, match="immutable"):
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        UPDATE external_channel_connections
                        SET app_mode = 'single'
                        WHERE id = 'multi-probe'
                        """
                    )
                )
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "DELETE FROM external_channel_connections WHERE id = 'multi-probe'"
                )
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO external_channel_connections (
                        id, workspace_id, provider, transport, status
                    )
                    VALUES ('old-writer', 'w', 'slack', 'socket', 'configuring')
                    """
                )
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO external_channel_agent_routes (
                        id, connection_id, agent_id, route_mode
                    )
                    VALUES ('old-writer-route', 'old-writer', 'a', 'dedicated')
                    """
                )
            )
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        """
                    SELECT app_mode FROM external_channel_connections
                    WHERE id = 'old-writer'
                    """
                    )
                )
                == "single"
            )
            assert connection.execute(
                sa.text(
                    """
                    SELECT connection_app_mode, catalog_status
                    FROM external_channel_agent_routes
                    WHERE id = 'old-writer-route'
                    """
                )
            ).one() == ("single", "available")
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "DELETE FROM external_channel_agent_routes "
                    "WHERE id = 'old-writer-route'"
                )
            )
            connection.execute(
                sa.text(
                    "DELETE FROM external_channel_connections WHERE id = 'old-writer'"
                )
            )

        alembic_command.downgrade(config, _PARENT_REVISION)
        with engine.connect() as connection:
            assert _snapshot(connection) == before
    finally:
        _close(database)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("zero_route", "exactly one dedicated route"),
        ("multiple_distinct_routes", "exactly one dedicated route"),
        ("non_dedicated", "exactly one dedicated route"),
        ("duplicate_association", "duplicate connection-Agent route"),
        ("cross_workspace", "route crosses Workspace boundary"),
        ("multiple_active_bindings", "resource has multiple active bindings"),
    ],
)
def test_external_channel_app_mode_migration_rejects_each_legacy_ambiguity(
    check_docker_availability: None,
    case: str,
    message: str,
) -> None:
    """Every preflight reports its own ambiguity before schema mutation."""
    del check_docker_availability
    database = _database()
    config, engine = next(database)
    try:
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_identity_graph(connection)
            if case == "zero_route":
                pass
            elif case == "multiple_distinct_routes":
                _insert_route(connection, route_id="route", agent_id="a")
                _insert_agent(connection, agent_id="a2", workspace_id="w")
                _insert_route(
                    connection,
                    route_id="route-2",
                    agent_id="a2",
                    route_mode="platform",
                )
            elif case == "non_dedicated":
                _insert_route(
                    connection,
                    route_id="route",
                    agent_id="a",
                    route_mode="platform",
                )
            elif case == "duplicate_association":
                _insert_route(connection, route_id="route", agent_id="a")
                _insert_route(
                    connection,
                    route_id="route-2",
                    agent_id="a",
                    route_mode="platform",
                )
            elif case == "cross_workspace":
                connection.execute(
                    sa.text(
                        "INSERT INTO workspaces (id, name, handle) "
                        "VALUES ('w2', 'W2', 'w2')"
                    )
                )
                _insert_agent(connection, agent_id="a2", workspace_id="w2")
                _insert_route(connection, route_id="route", agent_id="a2")
            elif case == "multiple_active_bindings":
                _insert_route(connection, route_id="route", agent_id="a")
                _insert_agent(connection, agent_id="a2", workspace_id="w")
                _insert_session(
                    connection, session_id="s2", workspace_id="w", agent_id="a2"
                )
                _insert_route(
                    connection,
                    route_id="route-2",
                    agent_id="a2",
                    route_mode="platform",
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO external_channel_resources (
                            id, connection_id, resource_type,
                            provider_resource_key, status
                        )
                        VALUES (
                            'resource', 'c', 'thread',
                            'slack:T1:C1:ambiguous', 'active'
                        )
                        """
                    )
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO external_channel_bindings (
                            id, resource_id, route_id, agent_session_id, status
                        )
                        VALUES
                            ('binding-1', 'resource', 'route', 's', 'active'),
                            ('binding-2', 'resource', 'route-2', 's2', 'active')
                        """
                    )
                )
            else:
                raise AssertionError(f"Unhandled ambiguity case: {case}")

        with pytest.raises(RuntimeError, match=message):
            alembic_command.upgrade(config, _REVISION)

        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        """
                    SELECT count(*)
                    FROM information_schema.columns
                    WHERE table_name = 'external_channel_connections'
                      AND column_name = 'app_mode'
                    """
                    )
                )
                == 0
            )
    finally:
        _close(database)


@pytest.mark.parametrize(
    "unsafe_state",
    (
        "multi_connection",
        "removed_catalog",
        "interaction",
        "conversation_admission",
        "channel_default",
        "invalid_parent_cardinality",
    ),
)
def test_external_channel_app_mode_migration_rejects_unsafe_downgrade(
    check_docker_availability: None,
    unsafe_state: str,
) -> None:
    """Downgrade never discards Phase 1-only or parent-incompatible state."""
    del check_docker_availability
    database = _database()
    config, engine = next(database)
    try:
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_valid_parent_graph(connection)
        alembic_command.upgrade(config, _REVISION)
        with engine.begin() as connection:
            if unsafe_state == "multi_connection":
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO external_channel_connections (
                            id, workspace_id, provider, transport, status, app_mode
                        )
                        VALUES ('multi-connection', 'w', 'slack', 'socket',
                                'configuring', 'multi')
                        """
                    )
                )
            elif unsafe_state == "removed_catalog":
                connection.execute(
                    sa.text(
                        """
                        UPDATE external_channel_agent_routes
                        SET catalog_status = 'removed', catalog_removed_at = now(),
                            catalog_removed_by_user_id = 'u'
                        WHERE id = 'route'
                        """
                    )
                )
            elif unsafe_state == "interaction":
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO external_channel_interactions (
                            id, connection_id, transport, provider_interaction_key,
                            interaction_type, projection, status, expires_at
                        )
                        VALUES (
                            'interaction', 'c', 'http', 'interaction-key',
                            'shortcut', '{}'::jsonb, 'accepted',
                            now() + interval '1 day'
                        )
                        """
                    )
                )
            elif unsafe_state == "conversation_admission":
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO external_channel_conversation_admissions (
                            id, connection_id, resource_id, source_message_id, origin,
                            status, expires_at
                        )
                        VALUES ('admission', 'c', 'resource', 'message', 'shortcut',
                                'pending_selection', now() + interval '1 day')
                        """
                    )
                )
            elif unsafe_state == "channel_default":
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO external_channel_channel_defaults (
                            id, connection_id, provider_channel_id, route_id, status,
                            configured_by_user_id
                        )
                        VALUES ('default', 'c', 'C1', 'route', 'active', 'u')
                        """
                    )
                )
            elif unsafe_state == "invalid_parent_cardinality":
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO external_channel_connections (
                            id, workspace_id, provider, transport, status, app_mode
                        )
                        VALUES ('unrouted', 'w', 'slack', 'http', 'active', 'single')
                        """
                    )
                )
            else:
                raise AssertionError(
                    f"Unhandled unsafe downgrade state: {unsafe_state}"
                )

        with pytest.raises(RuntimeError, match="Cannot downgrade"):
            alembic_command.downgrade(config, _PARENT_REVISION)
    finally:
        _close(database)
