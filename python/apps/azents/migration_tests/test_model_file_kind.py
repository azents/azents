"""Focused data-preservation regressions for the ModelFile kind conversion."""

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
    revision = directory.get_revision("7968012d878c")
    assert revision is not None
    assert revision.down_revision == "3ac042ea72bd"
    return revision.module


def test_kind_conversion_preserves_values_and_downgrades_losslessly(
    alembic_engine: Engine,
) -> None:
    """Exercise the actual revision on its one-column boundary, preserving rows."""
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE model_files "
                "(id integer PRIMARY KEY, kind varchar(32) NOT NULL)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO model_files VALUES "
                "(1, 'image'), (2, 'document'), (3, 'text'), (4, 'binary')"
            )
        )
        before = connection.execute(
            sa.text("SELECT * FROM model_files ORDER BY id")
        ).all()
        with Operations.context(MigrationContext.configure(connection)):
            _revision().upgrade()
        assert (
            connection.scalar(
                sa.text("SELECT pg_typeof(kind)::text FROM model_files LIMIT 1")
            )
            == "model_file_kind"
        )
        assert (
            connection.execute(
                sa.text("SELECT id, kind::text FROM model_files ORDER BY id")
            ).all()
            == before
        )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    sa.text("INSERT INTO model_files VALUES (5, 'unknown')")
                )
        with Operations.context(MigrationContext.configure(connection)):
            _revision().downgrade()
        assert (
            connection.execute(sa.text("SELECT * FROM model_files ORDER BY id")).all()
            == before
        )
        assert (
            connection.scalar(sa.text("SELECT to_regtype('model_file_kind')")) is None
        )


def test_unknown_retained_kind_stops_before_enum_creation(
    alembic_engine: Engine,
) -> None:
    """Unknown historical data must stay unchanged rather than being coerced."""
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE model_files "
                "(id integer PRIMARY KEY, kind varchar(32) NOT NULL)"
            )
        )
        connection.execute(
            sa.text("INSERT INTO model_files VALUES (1, 'historical-unknown')")
        )
    with pytest.raises(DBAPIError, match="Unsupported retained ModelFile kind"):
        with alembic_engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                _revision().upgrade()
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT kind FROM model_files"))
            == "historical-unknown"
        )
        assert (
            connection.scalar(sa.text("SELECT to_regtype('model_file_kind')")) is None
        )
