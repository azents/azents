"""Migration tests for retained External Channel route Agent provenance."""

import importlib
from typing import Any, cast

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from sqlalchemy.exc import DBAPIError

_app_mode_migration = cast(
    Any,
    importlib.import_module("azents.rdb.external_channel_app_mode_migration_test"),
)
_close = _app_mode_migration._close
_database = _app_mode_migration._database
_insert_agent = _app_mode_migration._insert_agent
_seed_valid_parent_graph = _app_mode_migration._seed_valid_parent_graph

_PARENT_REVISION = "00ae8d1fd42c"
_REVISION = "cc31dfa97a1b"


def test_external_channel_route_agent_history_migration(
    check_docker_availability: None,
) -> None:
    """Upgrade preserves provenance, fences active routing, and fails safe backward."""
    del check_docker_availability
    database = _database()
    config, engine = next(database)
    try:
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_valid_parent_graph(connection)
            _insert_agent(connection, agent_id="history-agent", workspace_id="w")
            connection.execute(
                sa.text(
                    """
                    INSERT INTO external_channel_connections (
                        id, workspace_id, provider, transport, status
                    )
                    VALUES (
                        'history-connection', 'w', 'slack', 'http', 'configuring'
                    )
                    """
                )
            )

        alembic_command.upgrade(config, _REVISION)

        with engine.connect() as connection:
            assert connection.execute(
                sa.text(
                    """
                    SELECT agent_id, agent_id_snapshot
                    FROM external_channel_agent_routes
                    WHERE id = 'route'
                    """
                )
            ).one() == ("a", "a")

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO external_channel_agent_routes (
                        id, connection_id, agent_id, route_mode
                    )
                    VALUES (
                        'history-route',
                        'history-connection',
                        'history-agent',
                        'dedicated'
                    )
                    """
                )
            )
        with engine.connect() as connection:
            assert connection.execute(
                sa.text(
                    """
                    SELECT agent_id, agent_id_snapshot
                    FROM external_channel_agent_routes
                    WHERE id = 'history-route'
                    """
                )
            ).one() == ("history-agent", "history-agent")

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO external_channel_agent_routes (
                            id, connection_id, agent_id, route_mode
                        )
                        VALUES (
                            'duplicate-history-route',
                            'history-connection',
                            'history-agent',
                            'dedicated'
                        )
                        """
                    )
                )

        with pytest.raises(DBAPIError, match="immutable"):
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        UPDATE external_channel_agent_routes
                        SET agent_id_snapshot = 'a'
                        WHERE id = 'history-route'
                        """
                    )
                )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        UPDATE external_channel_agent_routes
                        SET agent_id = NULL
                        WHERE id = 'history-route'
                        """
                    )
                )

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE external_channel_agent_routes
                    SET catalog_status = 'removed',
                        catalog_removed_at = now(),
                        agent_id = NULL
                    WHERE id = 'history-route'
                    """
                )
            )
            connection.execute(sa.text("DELETE FROM agents WHERE id = 'history-agent'"))
        with engine.connect() as connection:
            assert connection.execute(
                sa.text(
                    """
                    SELECT agent_id, agent_id_snapshot, catalog_status
                    FROM external_channel_agent_routes
                    WHERE id = 'history-route'
                    """
                )
            ).one() == (None, "history-agent", "removed")

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        UPDATE external_channel_agent_routes
                        SET catalog_status = 'available',
                            catalog_removed_at = NULL
                        WHERE id = 'history-route'
                        """
                    )
                )

        with pytest.raises(RuntimeError, match="detached route exists"):
            alembic_command.downgrade(config, _PARENT_REVISION)

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "DELETE FROM external_channel_agent_routes "
                    "WHERE id = 'history-route'"
                )
            )
            connection.execute(
                sa.text(
                    "DELETE FROM external_channel_connections "
                    "WHERE id = 'history-connection'"
                )
            )
        alembic_command.downgrade(config, _PARENT_REVISION)
    finally:
        _close(database)
