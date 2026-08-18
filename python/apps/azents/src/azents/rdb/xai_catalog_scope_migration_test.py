"""PostgreSQL migration tests for xAI integration-owned catalogs."""

from collections.abc import Generator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "30c55c0ef241"
_XAI_CATALOG_REVISION = "5c044388362c"


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


def _seed_xai_integrations_and_system_catalogs(engine: sa.Engine) -> None:
    """Seed both xAI credential products and their obsolete system catalogs."""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO workspaces (id, name, handle)
                VALUES (
                    'workspace-xai-catalog-migration',
                    'xAI migration',
                    'xai-migration'
                )
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
                VALUES
                    (
                        'integration-xai-api-key',
                        'workspace-xai-catalog-migration',
                        'xai',
                        'xAI API key',
                        'encrypted-api-key',
                        NULL,
                        TRUE
                    ),
                    (
                        'integration-xai-oauth',
                        'workspace-xai-catalog-migration',
                        'xai_oauth',
                        'xAI Grok OAuth',
                        'encrypted-oauth-token',
                        '{"type":"xai_oauth","status":"connected","connection_method":"device"}'::jsonb,
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
                    provider_integration_id
                )
                VALUES
                    ('system-catalog-xai', 'system', 'xai', 'litellm', NULL),
                    (
                        'system-catalog-xai-oauth',
                        'system',
                        'xai_oauth',
                        'litellm',
                        NULL
                    ),
                    ('system-catalog-openai', 'system', 'openai', 'litellm', NULL)
                """
            )
        )


def _catalog_rows(engine: sa.Engine) -> set[tuple[str, str, str | None]]:
    """Return provider, scope, and integration ownership rows."""
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                """
                SELECT provider::text, scope::text, provider_integration_id
                FROM llm_catalogs
                """
            )
        )
        return {(row[0], row[1], row[2]) for row in rows}


def test_xai_catalog_scope_migration_round_trips(
    check_docker_availability: None,
) -> None:
    """Backfill integration catalogs and remove only xAI system ownership."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        _seed_xai_integrations_and_system_catalogs(engine)

        alembic_command.upgrade(config, _XAI_CATALOG_REVISION)
        upgraded = _catalog_rows(engine)
        assert ("xai", "system", None) not in upgraded
        assert ("xai_oauth", "system", None) not in upgraded
        assert ("openai", "system", None) in upgraded
        assert (
            "xai",
            "integration",
            "integration-xai-api-key",
        ) in upgraded
        assert (
            "xai_oauth",
            "integration",
            "integration-xai-oauth",
        ) in upgraded

        alembic_command.downgrade(config, _PARENT_REVISION)
        downgraded = _catalog_rows(engine)
        assert ("xai", "system", None) in downgraded
        assert ("xai_oauth", "system", None) in downgraded
        assert (
            "xai",
            "integration",
            "integration-xai-api-key",
        ) in downgraded
        assert (
            "xai_oauth",
            "integration",
            "integration-xai-oauth",
        ) in downgraded

        alembic_command.upgrade(config, _XAI_CATALOG_REVISION)
        upgraded_again = _catalog_rows(engine)
        assert ("xai", "system", None) not in upgraded_again
        assert ("xai_oauth", "system", None) not in upgraded_again
        assert (
            sum(
                provider in {"xai", "xai_oauth"} and scope == "integration"
                for provider, scope, _integration_id in upgraded_again
            )
            == 2
        )
