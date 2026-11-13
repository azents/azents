"""Lossless supported-locale conversion and fail-closed historical data checks."""

from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from azents.consts import PROJECT_ROOT


def _revision() -> ModuleType:
    directory = ScriptDirectory.from_config(
        Config(PROJECT_ROOT / "db-schemas/rdb/alembic.ini")
    )
    revision = directory.get_revision("aed428366a0a")
    assert revision is not None
    assert revision.down_revision == "090e27a51823"
    return revision.module


def _create_users(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            "CREATE TABLE users (id integer PRIMARY KEY, "
            "locale varchar(35) NOT NULL DEFAULT 'en-US')"
        )
    )


def test_locale_conversion_preserves_values_default_and_downgrade(
    alembic_engine: Engine,
) -> None:
    with alembic_engine.begin() as connection:
        _create_users(connection)
        connection.execute(
            sa.text(
                "INSERT INTO users VALUES "
                "(1, 'en-US'), (2, 'ko-KR'), (3, 'ja-JP'), (4, 'fr-FR')"
            )
        )
        before = connection.execute(sa.text("SELECT * FROM users ORDER BY id")).all()
        with Operations.context(MigrationContext.configure(connection)):
            _revision().upgrade()
        assert (
            connection.execute(
                sa.text("SELECT id, locale::text FROM users ORDER BY id")
            ).all()
            == before
        )
        assert (
            connection.scalar(
                sa.text("SELECT pg_typeof(locale)::text FROM users LIMIT 1")
            )
            == "user_locale"
        )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(sa.text("INSERT INTO users VALUES (5, 'unknown')"))
        connection.execute(sa.text("INSERT INTO users (id) VALUES (6)"))
        assert (
            connection.scalar(sa.text("SELECT locale FROM users WHERE id=6")) == "en-US"
        )
        with Operations.context(MigrationContext.configure(connection)):
            _revision().downgrade()
        assert (
            connection.execute(
                sa.text("SELECT * FROM users WHERE id<6 ORDER BY id")
            ).all()
            == before
        )
        connection.execute(sa.text("INSERT INTO users (id) VALUES (7)"))
        assert (
            connection.scalar(sa.text("SELECT locale FROM users WHERE id=7")) == "en-US"
        )
        assert connection.scalar(sa.text("SELECT to_regtype('user_locale')")) is None


def test_unknown_locale_aborts_before_type_creation(alembic_engine: Engine) -> None:
    with alembic_engine.begin() as connection:
        _create_users(connection)
        connection.execute(
            sa.text("INSERT INTO users VALUES (1, 'historical-unknown')")
        )
    with pytest.raises(DBAPIError, match="Unsupported retained user locale"):
        with alembic_engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                _revision().upgrade()
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT locale FROM users"))
            == "historical-unknown"
        )
        assert connection.scalar(sa.text("SELECT to_regtype('user_locale')")) is None
