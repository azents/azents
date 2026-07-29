"""Migration tests for active Discord file capability snapshots."""

import json
from collections.abc import Generator, Mapping

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "785dfb44ef23"
_CAPABILITY_REVISION = "cb091fe69575"
_LEGACY_CAPABILITIES = {
    "interaction_public_key": "public-key",
    "message_command_id": "command-id",
    "provider_metadata": "preserved",
}
_DISCORD_CAPABILITIES = {
    "provider": "discord",
    "transport": "http",
    "inbound_events": True,
    "thread_history": True,
    "post_messages": True,
    "update_messages": True,
    "delete_messages": True,
    "download_files": True,
    "upload_files": True,
}


def _migration_database() -> Generator[tuple[AlembicConfig, sa.Engine], None, None]:
    with PostgresContainer(
        "postgres:17",
        driver="psycopg",
    ) as postgres:
        url = postgres.get_connection_url()
        config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        engine = sa.create_engine(url)
        try:
            yield config, engine
        finally:
            engine.dispose()


def _insert_connection(
    connection: sa.Connection,
    *,
    connection_id: str,
    provider: str,
    status: str,
    capabilities: Mapping[str, object] | None,
) -> None:
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_connections (
                id,
                workspace_id,
                provider,
                transport,
                ingress_profile,
                status,
                capabilities
            )
            VALUES (
                :id,
                'workspace-discord-capabilities',
                :provider,
                'http',
                :ingress_profile,
                :status,
                CAST(:capabilities AS jsonb)
            )
            """
        ),
        {
            "id": connection_id,
            "provider": provider,
            "ingress_profile": (
                "discord_gateway_http" if provider == "discord" else "slack_http"
            ),
            "status": status,
            "capabilities": (
                None if capabilities is None else json.dumps(capabilities)
            ),
        },
    )


def _capabilities_by_id(connection: sa.Connection) -> dict[str, object]:
    return {
        row.id: row.capabilities
        for row in connection.execute(
            sa.text(
                """
                SELECT id, capabilities
                FROM external_channel_connections
                ORDER BY id
                """
            )
        ).mappings()
    }


def test_discord_file_capability_migration_round_trip(
    check_docker_availability: None,
) -> None:
    """Only usable, fully activated Discord connections gain file capabilities."""
    del check_docker_availability
    migration_database = _migration_database()
    config, engine = next(migration_database)
    try:
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO workspaces (id, name, handle)
                    VALUES (
                        'workspace-discord-capabilities',
                        'Discord capability migration',
                        'discord-capability-migration'
                    )
                    """
                )
            )
            _insert_connection(
                connection,
                connection_id="discord-active",
                provider="discord",
                status="active",
                capabilities=_LEGACY_CAPABILITIES,
            )
            _insert_connection(
                connection,
                connection_id="discord-degraded",
                provider="discord",
                status="degraded",
                capabilities=_LEGACY_CAPABILITIES,
            )
            _insert_connection(
                connection,
                connection_id="discord-reconnect",
                provider="discord",
                status="reconnect_required",
                capabilities=_LEGACY_CAPABILITIES,
            )
            _insert_connection(
                connection,
                connection_id="discord-provisional",
                provider="discord",
                status="active",
                capabilities={"interaction_public_key": "public-key"},
            )
            _insert_connection(
                connection,
                connection_id="discord-null",
                provider="discord",
                status="active",
                capabilities=None,
            )
            _insert_connection(
                connection,
                connection_id="slack-active",
                provider="slack",
                status="active",
                capabilities=_LEGACY_CAPABILITIES,
            )

        alembic_command.upgrade(config, _CAPABILITY_REVISION)
        with engine.connect() as connection:
            capabilities = _capabilities_by_id(connection)
        expected = _LEGACY_CAPABILITIES | _DISCORD_CAPABILITIES
        assert capabilities["discord-active"] == expected
        assert capabilities["discord-degraded"] == expected
        assert capabilities["discord-reconnect"] == _LEGACY_CAPABILITIES
        assert capabilities["discord-provisional"] == {
            "interaction_public_key": "public-key"
        }
        assert capabilities["discord-null"] is None
        assert capabilities["slack-active"] == _LEGACY_CAPABILITIES

        alembic_command.downgrade(config, _PARENT_REVISION)
        with engine.connect() as connection:
            capabilities = _capabilities_by_id(connection)
        assert capabilities["discord-active"] == _LEGACY_CAPABILITIES
        assert capabilities["discord-degraded"] == _LEGACY_CAPABILITIES
        assert capabilities["discord-reconnect"] == _LEGACY_CAPABILITIES
        assert capabilities["discord-provisional"] == {
            "interaction_public_key": "public-key"
        }
        assert capabilities["discord-null"] is None
        assert capabilities["slack-active"] == _LEGACY_CAPABILITIES
    finally:
        migration_database.close()
