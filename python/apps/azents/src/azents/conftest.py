"""Test fixture settings."""

from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncGenerator, Generator

import pytest
import pytest_asyncio
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from azcommon.testing.images import get_docker_hub_image
from docker.errors import DockerException, ImageNotFound
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    AsyncTransaction,
    create_async_engine,
)
from testcontainers.core.docker_client import (
    DockerClient,
)
from testcontainers.postgres import (
    PostgresContainer,
)
from testcontainers.redis import (
    RedisContainer,
)

from azents.consts import PROJECT_ROOT
from azents.rdb.session import SessionManager

#
# Docker
#


def _docker_availability() -> bool:
    try:
        DockerClient().client.ping()
        return True
    except DockerException:
        return False


def _ensure_docker_image(image: str) -> str:
    docker_client = DockerClient().client
    try:
        docker_client.images.get(image)
    except ImageNotFound:
        docker_client.images.pull(image)
    return image


@pytest.fixture(scope="session")
def check_docker_availability() -> None:
    if not _docker_availability():
        pytest.skip("Docker is not available")


#
# RDB fixtures
#


@pytest.fixture(scope="session")
def postgres_container(
    check_docker_availability: None,
) -> Generator[PostgresContainer, None, None]:
    """PostgreSQL test container."""
    postgres_image = _ensure_docker_image(get_docker_hub_image("postgres:17"))
    with PostgresContainer(
        postgres_image,
        driver="psycopg",
    ) as postgres:
        yield postgres


@pytest.fixture(scope="session")
def latest_db_schema(
    postgres_container: PostgresContainer,
) -> Generator[None, None, None]:
    """Apply the latest RDB schema for tests."""
    alembic_config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
    alembic_config.set_main_option(
        "sqlalchemy.url",
        postgres_container.get_connection_url().replace("%", "%%"),
    )
    alembic_command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        alembic_command.downgrade(alembic_config, "base")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def rdb_engine(
    postgres_container: PostgresContainer,
) -> AsyncGenerator[AsyncEngine, None]:
    """SQLAlchemy async engine fixture."""
    engine = create_async_engine(postgres_container.get_connection_url(), echo=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def rdb_session_manager(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> AsyncGenerator[SessionManager[AsyncSession], None]:
    """SessionManager fixture with auto-commit/rollback and test rollback.

    This mirrors the production session manager's auto-commit/rollback behavior,
    but wraps each test in a savepoint so the full test transaction rolls back.
    """
    async with rdb_engine.connect() as connection:

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            async with AsyncExitStack() as stack:
                async_session = await stack.enter_async_context(
                    AsyncSession(bind=connection, expire_on_commit=False)
                )
                nested: AsyncTransaction = await connection.begin_nested()

                @event.listens_for(async_session.sync_session, "after_transaction_end")
                def end_savepoint(  # pyright: ignore[reportUnusedFunction]
                    _session: Any,  # noqa: ANN401
                    _transaction: Any,  # noqa: ANN401
                ) -> None:
                    # Use Any because sync_session transaction internals are private
                    # types.
                    nonlocal nested
                    if not nested.is_active:
                        nested = connection.begin_nested()

                try:
                    yield async_session
                except Exception:
                    await async_session.rollback()
                    raise
                else:
                    await async_session.commit()

        tx = await connection.begin()
        try:
            yield session_manager
        finally:
            await tx.rollback()


@pytest_asyncio.fixture(scope="function")
async def rdb_session(
    rdb_session_manager: SessionManager[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """SQLAlchemy session fixture."""
    async with rdb_session_manager() as session:
        yield session


#
# Redis fixtures
#


@pytest.fixture(scope="session")
def redis_container(
    check_docker_availability: None,
) -> Generator[RedisContainer, None, None]:
    """Redis test container."""
    valkey_image = _ensure_docker_image("public.ecr.aws/valkey/valkey:9-alpine")
    with RedisContainer(
        valkey_image,
    ) as redis:
        yield redis


@pytest.fixture(scope="session")
def redis_url(redis_container: RedisContainer) -> str:
    """Redis connection URL."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}"
