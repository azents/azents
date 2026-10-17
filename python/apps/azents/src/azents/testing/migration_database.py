"""Physically isolated PostgreSQL databases for migration contract tests."""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4

import sqlalchemy as sa
from alembic.config import Config as AlembicConfig
from sqlalchemy.engine import Engine
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT


@dataclass(frozen=True)
class MigrationDatabase:
    """Disposable database identity and its real Alembic connection."""

    name: str
    engine: Engine
    config: AlembicConfig


@contextmanager
def isolated_migration_database(
    postgres: PostgresContainer, *, template: str | None
) -> Generator[MigrationDatabase]:
    """Clone only immutable setup bytes; each caller owns distinct physical data."""
    name = "migration_fixture_" + uuid4().hex
    admin = sa.create_engine(
        postgres.get_connection_url(), isolation_level="AUTOCOMMIT"
    )
    quote = admin.dialect.identifier_preparer.quote_identifier
    source = "" if template is None else f" TEMPLATE {quote(template)}"
    engine: Engine | None = None
    created = False
    try:
        with admin.connect() as connection:
            connection.execute(sa.text(f"CREATE DATABASE {quote(name)}{source}"))
        created = True
        url = sa.engine.make_url(postgres.get_connection_url()).set(database=name)
        config = AlembicConfig(PROJECT_ROOT / "db-schemas/rdb/alembic.ini")
        config.set_main_option(
            "sqlalchemy.url",
            url.render_as_string(hide_password=False).replace("%", "%%"),
        )
        engine = sa.create_engine(url)
        yield MigrationDatabase(name=name, engine=engine, config=config)
    finally:
        if engine is not None:
            engine.dispose()
        try:
            if created:
                with admin.connect() as connection:
                    connection.execute(
                        sa.text(f"DROP DATABASE {quote(name)} WITH (FORCE)")
                    )
        finally:
            admin.dispose()
