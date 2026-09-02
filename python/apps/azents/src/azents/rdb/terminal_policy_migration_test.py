"""Migration tests for default-enabled Runtime Terminal policy columns."""

from collections.abc import Generator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "a66397c7eabc"
_TERMINAL_POLICY_REVISION = "82df4f970f57"
_SHELL_REMOVAL_REVISION = "7de5749cadd5"


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


def test_terminal_policy_migration_defaults_existing_rows_and_round_trips(
    check_docker_availability: None,
) -> None:
    """All three policy sources backfill true and cleanly downgrade."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        _insert_parent_rows(engine)

        alembic_command.upgrade(config, _TERMINAL_POLICY_REVISION)
        inspector = sa.inspect(engine)
        for table in (
            "runtime_infrastructure_profiles",
            "workspace_runtime_profiles",
            "agents",
        ):
            terminal_column = next(
                column
                for column in inspector.get_columns(table)
                if column["name"] == "terminal_enabled"
            )
            assert terminal_column["nullable"] is False
            assert terminal_column["default"] in {"true", "true()"}
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        sa.text(f"SELECT terminal_enabled FROM {table} LIMIT 1")
                    )
                    is True
                )

        alembic_command.downgrade(config, _PARENT_REVISION)
        inspector = sa.inspect(engine)
        for table in (
            "runtime_infrastructure_profiles",
            "workspace_runtime_profiles",
            "agents",
        ):
            assert "terminal_enabled" not in {
                column["name"] for column in inspector.get_columns(table)
            }

        alembic_command.upgrade(config, _TERMINAL_POLICY_REVISION)
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text("SELECT terminal_enabled FROM agents LIMIT 1")
                )
                is True
            )


def test_shell_policy_removal_drops_and_restores_default_enabled_column(
    check_docker_availability: None,
) -> None:
    """The obsolete Agent Shell column drops and cleanly restores on downgrade."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        _insert_parent_rows(engine)

        alembic_command.upgrade(config, _SHELL_REMOVAL_REVISION)
        assert "shell_enabled" not in {
            column["name"] for column in sa.inspect(engine).get_columns("agents")
        }

        alembic_command.downgrade(config, _TERMINAL_POLICY_REVISION)
        shell_column = next(
            column
            for column in sa.inspect(engine).get_columns("agents")
            if column["name"] == "shell_enabled"
        )
        assert shell_column["nullable"] is False
        assert shell_column["default"] in {"true", "true()"}
        with engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT shell_enabled FROM agents LIMIT 1"))
                is True
            )

        alembic_command.upgrade(config, _SHELL_REMOVAL_REVISION)
        assert "shell_enabled" not in {
            column["name"] for column in sa.inspect(engine).get_columns("agents")
        }


def _insert_parent_rows(engine: sa.Engine) -> None:
    """Insert one linked pre-migration row at every Terminal policy scope."""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO workspaces (id, name, handle)
                VALUES (:id, :name, :handle)
                """
            ),
            {
                "id": "1" * 32,
                "name": "Terminal migration",
                "handle": "terminal-migration",
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO runtime_providers (
                    id,
                    provider_id,
                    scope,
                    kind,
                    display_name,
                    capabilities
                )
                VALUES (
                    :id,
                    :provider_id,
                    'system',
                    'docker',
                    :display_name,
                    '{}'::jsonb
                )
                """
            ),
            {
                "id": "2" * 32,
                "provider_id": "terminal-migration-provider",
                "display_name": "Terminal migration provider",
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO runtime_infrastructure_profiles (
                    id,
                    provider_id,
                    profile_kind,
                    display_name,
                    description,
                    lifecycle,
                    contract_family,
                    schema_version,
                    spec,
                    required_capabilities,
                    version,
                    digest
                )
                VALUES (
                    :id,
                    :provider_id,
                    'docker_container',
                    :display_name,
                    :description,
                    'active',
                    :contract_family,
                    1,
                    '{}'::jsonb,
                    '[]'::jsonb,
                    1,
                    :digest
                )
                """
            ),
            {
                "id": "3" * 32,
                "provider_id": "2" * 32,
                "display_name": "Terminal migration infrastructure",
                "description": "Terminal migration infrastructure",
                "contract_family": "docker.container-profile",
                "digest": "a" * 64,
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO workspace_runtime_profiles (
                    id,
                    workspace_id,
                    provider_id,
                    infrastructure_profile_id,
                    display_name,
                    description,
                    lifecycle,
                    policy,
                    version,
                    digest
                )
                VALUES (
                    :id,
                    :workspace_id,
                    :provider_id,
                    :infrastructure_profile_id,
                    :display_name,
                    :description,
                    'active',
                    '{}'::jsonb,
                    1,
                    :digest
                )
                """
            ),
            {
                "id": "4" * 32,
                "workspace_id": "1" * 32,
                "provider_id": "2" * 32,
                "infrastructure_profile_id": "3" * 32,
                "display_name": "Terminal migration workspace",
                "description": "Terminal migration workspace",
                "digest": "b" * 64,
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO agents (
                    id,
                    workspace_id,
                    name,
                    model_selection,
                    lightweight_model_selection,
                    selectable_model_options,
                    main_model_label,
                    lightweight_model_label,
                    enabled,
                    type,
                    runtime_profile_id,
                    shell_enabled,
                    memory_enabled
                )
                VALUES (
                    :id,
                    :workspace_id,
                    :name,
                    '{}'::jsonb,
                    '{}'::jsonb,
                    '[{}]'::jsonb,
                    'default',
                    'default',
                    true,
                    'public',
                    :runtime_profile_id,
                    true,
                    true
                )
                """
            ),
            {
                "id": "5" * 32,
                "workspace_id": "1" * 32,
                "name": "Terminal migration agent",
                "runtime_profile_id": "4" * 32,
            },
        )
