"""Migration coverage for image-generation model catalogs."""

from collections.abc import Generator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.dialects import postgresql
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "6b53a0a15d11"
_IMAGE_CATALOG_REVISION = "dde8c8826107"


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


def _seed_conversation_catalog(engine: sa.Engine) -> None:
    """Seed integration catalog state that predates catalog purposes."""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO workspaces (id, name, handle)
                VALUES ('ws-image-migration', 'Image migration', 'image-migration')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO llm_provider_integrations (
                    id,
                    workspace_id,
                    provider,
                    name,
                    encrypted_credentials,
                    config,
                    enabled
                )
                VALUES (
                    'integration-image-migration',
                    'ws-image-migration',
                    'openai',
                    'OpenAI',
                    'encrypted',
                    NULL,
                    TRUE
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO llm_catalogs (
                    id,
                    scope,
                    provider,
                    lowerer_target,
                    provider_integration_id,
                    current_snapshot_id,
                    latest_attempt_id
                )
                VALUES (
                    'catalog-conversation',
                    'integration',
                    'openai',
                    'litellm',
                    'integration-image-migration',
                    'snapshot-conversation',
                    'attempt-conversation'
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO llm_catalog_snapshots (
                    id,
                    catalog_id,
                    entry_count,
                    visible_count,
                    hidden_count
                )
                VALUES ('snapshot-conversation', 'catalog-conversation', 0, 0, 0)
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO llm_catalog_sync_attempts (
                    id,
                    source_key,
                    status,
                    started_at,
                    fetched_count,
                    matched_count,
                    skipped_count,
                    hidden_count,
                    catalog_id
                )
                VALUES (
                    'attempt-conversation',
                    'model-list',
                    'succeeded',
                    now(),
                    0,
                    0,
                    0,
                    0,
                    'catalog-conversation'
                )
                """
            )
        )


def test_image_generation_catalog_migration_round_trips(
    check_docker_availability: None,
) -> None:
    """Backfill conversation state and discard image catalogs on downgrade."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        _seed_conversation_catalog(engine)

        alembic_command.upgrade(config, _IMAGE_CATALOG_REVISION)
        inspector = sa.inspect(engine)
        catalog_columns = {
            column["name"]: column for column in inspector.get_columns("llm_catalogs")
        }
        integration_columns = {
            column["name"]: column
            for column in inspector.get_columns("llm_provider_integrations")
        }
        snapshot_columns = {
            column["name"] for column in inspector.get_columns("llm_catalog_snapshots")
        }
        attempt_columns = {
            column["name"]
            for column in inspector.get_columns("llm_catalog_sync_attempts")
        }
        catalog_indexes = {
            index["name"] for index in inspector.get_indexes("llm_catalogs")
        }

        assert isinstance(catalog_columns["purpose"]["type"], postgresql.ENUM)
        assert catalog_columns["purpose"]["type"].name == "llm_catalog_purpose"
        assert integration_columns["catalog_configuration_version"]["nullable"] is False
        assert "catalog_configuration_version" in snapshot_columns
        assert "catalog_configuration_version" in attempt_columns
        assert "image_generation_catalog_entries" in inspector.get_table_names()
        assert "uq_llm_catalogs_integration_target_purpose" in catalog_indexes
        assert "uq_llm_catalogs_system_scope_provider_target_purpose" in catalog_indexes

        with engine.begin() as connection:
            row = connection.execute(
                sa.text(
                    """
                    SELECT
                        catalog.purpose::text,
                        integration.catalog_configuration_version,
                        snapshot.catalog_configuration_version,
                        attempt.catalog_configuration_version
                    FROM llm_catalogs AS catalog
                    JOIN llm_provider_integrations AS integration
                      ON integration.id = catalog.provider_integration_id
                    JOIN llm_catalog_snapshots AS snapshot
                      ON snapshot.catalog_id = catalog.id
                    JOIN llm_catalog_sync_attempts AS attempt
                      ON attempt.catalog_id = catalog.id
                    WHERE catalog.id = 'catalog-conversation'
                    """
                )
            ).one()
            assert tuple(row) == ("conversation", 1, 1, 1)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO llm_catalogs (
                        id,
                        scope,
                        provider,
                        purpose,
                        lowerer_target,
                        provider_integration_id
                    )
                    VALUES (
                        'catalog-image',
                        'integration',
                        'openai',
                        'image_generation',
                        'litellm',
                        'integration-image-migration'
                    )
                    """
                )
            )

        alembic_command.downgrade(config, _PARENT_REVISION)
        downgraded_inspector = sa.inspect(engine)
        assert "image_generation_catalog_entries" not in (
            downgraded_inspector.get_table_names()
        )
        assert "purpose" not in {
            column["name"]
            for column in downgraded_inspector.get_columns("llm_catalogs")
        }
        assert "catalog_configuration_version" not in {
            column["name"]
            for column in downgraded_inspector.get_columns("llm_provider_integrations")
        }
        with engine.connect() as connection:
            catalogs = connection.execute(
                sa.text("SELECT id FROM llm_catalogs ORDER BY id")
            ).scalars()
            assert list(catalogs) == ["catalog-conversation"]
