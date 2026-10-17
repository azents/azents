"""Native PostgreSQL clone isolation and disposable database cleanup."""

import pytest
import sqlalchemy as sa
from testcontainers.postgres import PostgresContainer

from azents.testing.migration_database import isolated_migration_database


def _database_exists(postgres: PostgresContainer, name: str) -> bool:
    engine = sa.create_engine(postgres.get_connection_url())
    try:
        with engine.connect() as connection:
            return bool(
                connection.scalar(
                    sa.text("SELECT count(*) FROM pg_database WHERE datname = :name"),
                    {"name": name},
                )
            )
    finally:
        engine.dispose()


def test_migration_database_clones_keep_independent_data_schema_and_revision(
    postgres_container: PostgresContainer,
) -> None:
    with isolated_migration_database(postgres_container, template=None) as source:
        with source.engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE seed (value text NOT NULL)"))
            connection.execute(sa.text("INSERT INTO seed VALUES ('historical')"))
            connection.execute(
                sa.text("CREATE TABLE alembic_version (version_num text NOT NULL)")
            )
            connection.execute(sa.text("INSERT INTO alembic_version VALUES ('parent')"))
        source.engine.dispose()
        with (
            isolated_migration_database(
                postgres_container, template=source.name
            ) as first,
            isolated_migration_database(
                postgres_container, template=source.name
            ) as second,
        ):
            assert len({source.name, first.name, second.name}) == 3
            with first.engine.begin() as connection:
                connection.execute(sa.text("DROP TABLE seed"))
                connection.execute(
                    sa.text("UPDATE alembic_version SET version_num='cut'")
                )
            for engine in (second.engine, source.engine):
                with engine.connect() as connection:
                    assert connection.scalar(sa.text("SELECT value FROM seed")) == (
                        "historical"
                    )
                    assert (
                        connection.scalar(
                            sa.text("SELECT version_num FROM alembic_version")
                        )
                        == "parent"
                    )
        assert not _database_exists(postgres_container, first.name)
        assert not _database_exists(postgres_container, second.name)
    assert not _database_exists(postgres_container, source.name)


def test_migration_database_cleans_up_after_failed_test(
    postgres_container: PostgresContainer,
) -> None:
    with pytest.raises(RuntimeError, match="synthetic test failure"):
        with isolated_migration_database(postgres_container, template=None) as isolated:
            name = isolated.name
            raise RuntimeError("synthetic test failure")
    assert not _database_exists(postgres_container, name)
