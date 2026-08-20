"""PostgreSQL migration tests for Discord Thread archive policy."""

from collections.abc import Generator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "936373d16d53"
_POLICY_REVISION = "ff79e1119f1d"


@contextmanager
def _migration_database() -> Generator[tuple[AlembicConfig, sa.Engine]]:
    """Create an isolated PostgreSQL database for migration verification."""
    with PostgresContainer("postgres:17", driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        engine = sa.create_engine(url)
        try:
            yield config, engine
        finally:
            engine.dispose()


def _seed_connections(engine: sa.Engine) -> None:
    """Seed Discord and Slack rows with representative configuration."""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO workspaces (id, name, handle)
                VALUES ('workspace-thread-policy', 'Thread policy', 'thread-policy')
                """
            )
        )
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
                    app_mode,
                    provider_config
                )
                VALUES
                    (
                        'discord-active',
                        'workspace-thread-policy',
                        'discord',
                        'http',
                        'discord_gateway_http',
                        'active',
                        'single',
                        '{"provider":"discord","target_guild_id":"guild-1","custom":"kept"}'::jsonb
                    ),
                    (
                        'discord-disconnected',
                        'workspace-thread-policy',
                        'discord',
                        'http',
                        'discord_gateway_http',
                        'disconnected',
                        'multi',
                        '{"provider":"discord","target_guild_id":"guild-2"}'::jsonb
                    ),
                    (
                        'slack-active',
                        'workspace-thread-policy',
                        'slack',
                        'http',
                        'slack_http',
                        'active',
                        'single',
                        '{"provider":"slack","custom":"unchanged"}'::jsonb
                    )
                """
            )
        )


def _configurations(engine: sa.Engine) -> dict[str, dict[str, object]]:
    """Return provider configuration keyed by connection ID."""
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                """
                SELECT id, provider_config
                FROM external_channel_connections
                ORDER BY id
                """
            )
        )
        return {row[0]: row[1] for row in rows}


def test_discord_thread_archive_policy_migration_round_trips(
    check_docker_availability: None,
) -> None:
    """Backfill every Discord row while preserving unrelated JSON and Slack."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        _seed_connections(engine)

        alembic_command.upgrade(config, _POLICY_REVISION)
        upgraded = _configurations(engine)
        assert upgraded["discord-active"] == {
            "provider": "discord",
            "target_guild_id": "guild-1",
            "custom": "kept",
            "thread_auto_archive_duration_minutes": 1440,
        }
        assert (
            upgraded["discord-disconnected"]["thread_auto_archive_duration_minutes"]
            == 1440
        )
        assert upgraded["slack-active"] == {
            "provider": "slack",
            "custom": "unchanged",
        }

        alembic_command.downgrade(config, _PARENT_REVISION)
        downgraded = _configurations(engine)
        assert (
            "thread_auto_archive_duration_minutes" not in downgraded["discord-active"]
        )
        assert downgraded["discord-active"]["custom"] == "kept"
        assert downgraded["slack-active"] == {
            "provider": "slack",
            "custom": "unchanged",
        }
