"""Dedicated pytest-alembic fixtures for Azents RDB migrations."""

import os
from collections.abc import Generator

import pytest
import sqlalchemy as sa
from alembic.config import Config as AlembicConfig
from docker.errors import DockerException, ImageNotFound
from pytest_alembic.config import Config as PytestAlembicConfig
from testcontainers.core.docker_client import DockerClient
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_DATABASE_URL_ENV = "AZENTS_MIGRATION_TEST_DATABASE_URL"
_MINIMUM_DOWNGRADE_REVISION = "cb091fe69575"


def _docker_available() -> bool:
    """Return whether the local Docker daemon can run a PostgreSQL container."""
    try:
        DockerClient().client.ping()
        return True
    except DockerException:
        return False


def _postgres_image() -> str:
    """Ensure the migration-test PostgreSQL image is locally available."""
    docker_client = DockerClient().client
    image = "postgres:17"
    try:
        docker_client.images.get(image)
    except ImageNotFound:
        docker_client.images.pull(image)
    return image


@pytest.fixture(scope="session")
def migration_database_url() -> Generator[str, None, None]:
    """Provide one dedicated PostgreSQL database URL for the migration suite."""
    configured_url = os.environ.get(_DATABASE_URL_ENV)
    if configured_url:
        yield configured_url
        return
    if not _docker_available():
        pytest.skip(f"Docker is unavailable and {_DATABASE_URL_ENV} is not configured.")
    with PostgresContainer(
        _postgres_image(),
        driver="psycopg",
    ) as postgres:
        yield postgres.get_connection_url()


@pytest.fixture()
def alembic_engine(
    migration_database_url: str,
) -> Generator[sa.Engine, None, None]:
    """Reset and expose the PostgreSQL engine used by one Alembic test."""
    engine = sa.create_engine(migration_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(sa.text("CREATE SCHEMA public"))
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def alembic_config(
    migration_database_url: str,
) -> PytestAlembicConfig:
    """Configure pytest-alembic for the Azents RDB revision graph."""
    native_config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
    native_config.set_main_option(
        "sqlalchemy.url",
        migration_database_url.replace("%", "%%"),
    )
    return PytestAlembicConfig(
        alembic_config=native_config,
        minimum_downgrade_revision=_MINIMUM_DOWNGRADE_REVISION,
    )
