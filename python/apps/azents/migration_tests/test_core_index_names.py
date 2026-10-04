"""Regression checks for bounded, namespace-unique core index renames."""

import importlib
import io
from types import ModuleType

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from pytest_alembic.runner import MigrationContext as AlembicRunner
from sqlalchemy.engine import Engine

from azents.consts import PROJECT_ROOT
from azents.rdb.models.base import RDBModel

_PARENT = "66aa52336fc8"
_REVISION = "4ededb171886"


def _revision_module() -> ModuleType:
    for model in (
        "agent_avatar_cleanup",
        "agent_project_preset",
        "agent_runtime_add",
        "agent_runtime_removal",
        "artifact",
        "external_channel",
        "memory",
        "model_file",
        "runtime_profile",
        "session_agent_context",
    ):
        importlib.import_module(f"azents.rdb.models.{model}")
    directory = ScriptDirectory.from_config(
        Config(PROJECT_ROOT / "db-schemas/rdb/alembic.ini")
    )
    revision = directory.get_revision(_REVISION)
    assert revision is not None
    return revision.module


def test_core_index_offline_names_match_models() -> None:
    """Require unique bounded identifiers and exact offline/model agreement."""
    module = _revision_module()
    renames = module._INDEX_RENAMES
    assert len(renames) == 25
    names = [rename.new for rename in renames]
    assert len(names) == len(set(names))
    assert all(len(name.encode("utf-8")) <= 63 for name in names)
    indexes = [
        index for table in RDBModel.metadata.tables.values() for index in table.indexes
    ]
    for name in names:
        assert sum(index.name == name for index in indexes) == 1
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        module.upgrade()
    for rename in renames:
        assert (
            f'ALTER INDEX "{rename.old}" RENAME TO "{rename.new}";' in output.getvalue()
        )
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        module.downgrade()
    for rename in renames:
        assert (
            f'ALTER INDEX "{rename.new}" RENAME TO "{rename.old}";' in output.getvalue()
        )


def _definitions(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'"
            )
        )
        return {name: definition for name, definition in rows}


def test_core_index_forward_and_downgrade_preserve_definitions(
    alembic_runner: AlembicRunner, alembic_engine: Engine
) -> None:
    """Prove real PostgreSQL upgrades and downgrades preserve every index body."""
    alembic_runner.migrate_up_to(_PARENT)
    original = _definitions(alembic_engine)
    renames = _revision_module()._INDEX_RENAMES
    assert all(
        rename.old in original and rename.new not in original for rename in renames
    )
    alembic_runner.migrate_up_to(_REVISION)
    renamed = _definitions(alembic_engine)
    for rename in renames:
        assert rename.old not in renamed
        assert renamed[rename.new] == original[rename.old].replace(
            rename.old, rename.new, 1
        )
    # A same-column ordinary/partial-unique pair needs a naming authority decision.
    for name in (
        "ix_external_channel_agent_routes_connection_id",
        "uq_external_channel_agent_routes_single_connection",
        "ix_image_generation_catalog_entries_catalog_rank",
    ):
        assert renamed[name] == original[name]
    alembic_runner.migrate_down_to(_PARENT)
    assert _definitions(alembic_engine) == original
