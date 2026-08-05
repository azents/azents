"""Migration tests for the External Channel participation foundation."""

from collections.abc import Generator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT
from azents.rdb.models.external_channel import (
    external_channel_conversation_location_enum,
    external_channel_participation_setting_status_enum,
    external_channel_setup_claim_status_enum,
)

_PARENT_REVISION = "d0a55d801644"
_PARTICIPATION_REVISION = "772e7ab22a8e"
_HEAD_REVISION = "d51acb332a07"


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


def _enum_values(connection: sa.Connection, enum_name: str) -> list[str]:
    """Return ordered values for one installed PostgreSQL enum."""
    return list(
        connection.execute(
            sa.text(
                """
                SELECT enumlabel
                FROM pg_enum
                JOIN pg_type ON pg_type.oid = enumtypid
                WHERE typname = :enum_name
                ORDER BY enumsortorder
                """
            ),
            {"enum_name": enum_name},
        ).scalars()
    )


def _seed_thread_resource(connection: sa.Connection) -> None:
    """Seed one pre-feature thread Resource without participation state."""
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES (
                'ws-participation',
                'Participation migration',
                'participation-migration'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_connections (
                id, workspace_id, provider, transport, ingress_profile, status,
                app_mode, provider_app_id, provider_tenant_id, encrypted_credentials
            )
            VALUES (
                'conn-participation',
                'ws-participation',
                'slack',
                'http',
                'slack_http',
                'active',
                'single',
                'participation-app',
                'participation-tenant',
                'participation-ciphertext'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_resources (
                id, connection_id, resource_type, provider_resource_key, status
            )
            VALUES (
                'thread-participation',
                'conn-participation',
                'thread',
                'thread-before-participation',
                'active'
            )
            """
        )
    )


def test_participation_enum_models_do_not_own_postgresql_types() -> None:
    """Alembic, not SQLAlchemy model metadata, owns new enum lifecycle."""
    assert external_channel_conversation_location_enum.create_type is False
    assert external_channel_participation_setting_status_enum.create_type is False
    assert external_channel_setup_claim_status_enum.create_type is False
    assert (
        PROJECT_ROOT.joinpath("db-schemas", "rdb", "revision").read_text().strip()
        == _HEAD_REVISION
    )


def test_participation_migration_preserves_threads_and_guards_downgrade(
    check_docker_availability: None,
) -> None:
    """Upgrade is additive and downgrade stops after participation-only writes."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_thread_resource(connection)

        alembic_command.upgrade(config, _PARTICIPATION_REVISION)
        inspector = sa.inspect(engine)
        assert {
            "external_channel_participation_settings",
            "external_channel_setup_claims",
        } <= set(inspector.get_table_names())
        default_columns = {
            column["name"]: column
            for column in inspector.get_columns("external_channel_channel_defaults")
        }
        assert default_columns["configured_by_user_id"]["nullable"] is True
        assert default_columns["configured_by_principal_id"]["nullable"] is True
        assert {
            constraint["name"]
            for constraint in inspector.get_check_constraints(
                "external_channel_channel_defaults"
            )
        } >= {"ck_external_channel_channel_defaults_configured_actor"}
        participation_indexes = {
            index["name"]: index
            for index in inspector.get_indexes(
                "external_channel_participation_settings"
            )
        }
        active_index = participation_indexes[
            "uq_external_channel_participation_active_channel"
        ]
        assert active_index["unique"] is True
        assert active_index["column_names"] == [
            "connection_id",
            "provider_parent_channel_id",
        ]
        assert "route_id" not in active_index["column_names"]

        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        """
                    SELECT count(*) FROM external_channel_resources
                    WHERE id = 'thread-participation'
                      AND resource_type = 'thread'
                    """
                    )
                )
                == 1
            )
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM external_channel_participation_settings"
                    )
                )
                == 0
            )
            assert _enum_values(connection, "external_channel_resource_type") == [
                "parent_channel",
                "thread",
            ]
            delivery_values = _enum_values(
                connection, "external_channel_delivery_origin_type"
            )
            assert "setup_claim" in delivery_values
            assert "binding_settings_available" in delivery_values

        alembic_command.downgrade(config, _PARENT_REVISION)
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        """
                    SELECT count(*) FROM external_channel_resources
                    WHERE id = 'thread-participation'
                      AND resource_type = 'thread'
                    """
                    )
                )
                == 1
            )
            assert _enum_values(connection, "external_channel_resource_type") == [
                "thread"
            ]

        alembic_command.upgrade(config, _PARTICIPATION_REVISION)
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO external_channel_resources (
                        id, connection_id, resource_type, provider_resource_key, status
                    )
                    VALUES (
                        'parent-participation',
                        'conn-participation',
                        'parent_channel',
                        'C-PARTICIPATION',
                        'active'
                    )
                    """
                )
            )
        with pytest.raises(
            RuntimeError,
            match="participation state is written",
        ):
            alembic_command.downgrade(config, _PARENT_REVISION)

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    DELETE FROM external_channel_resources
                    WHERE id = 'parent-participation'
                    """
                )
            )
        alembic_command.downgrade(config, _PARENT_REVISION)
