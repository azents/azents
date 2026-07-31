"""Migration tests for External Channel binding status removal."""

import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT_REVISION = "aafb89c5904b"
_REVISION = "a3a7d36f4416"
_STATUS_ENUM = "external_channel_binding_status"
_PARENT_INDEXES = {
    "ix_external_channel_bindings_agent_session_id_status",
    "ix_external_channel_bindings_route_id_status",
    "uq_external_channel_bindings_active_resource",
}
_CURRENT_INDEXES = {
    "ix_external_channel_bindings_agent_session_id",
    "ix_external_channel_bindings_route_id",
    "uq_external_channel_bindings_connected_resource",
}


def _column_names(engine: Engine) -> set[str]:
    """Return External Channel binding column names."""
    return {
        column["name"]
        for column in sa.inspect(engine).get_columns("external_channel_bindings")
    }


def _index_names(engine: Engine) -> set[str]:
    """Return External Channel binding index names."""
    return {
        name
        for index in sa.inspect(engine).get_indexes("external_channel_bindings")
        if isinstance(name := index["name"], str)
    }


def _enum_names(engine: Engine) -> set[str]:
    """Return PostgreSQL enum type names in the migration schema."""
    with engine.connect() as connection:
        return set(
            connection.execute(
                sa.text(
                    """
                    SELECT typname
                    FROM pg_type
                    WHERE typtype = 'e'
                      AND typnamespace = to_regnamespace('public')
                    """
                )
            ).scalars()
        )


def test_binding_status_removal_round_trips_exact_schema(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Replace redundant status authority and restore it on downgrade."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)

    assert "status" in _column_names(alembic_engine)
    assert _STATUS_ENUM in _enum_names(alembic_engine)
    assert _PARENT_INDEXES <= _index_names(alembic_engine)
    assert _CURRENT_INDEXES.isdisjoint(_index_names(alembic_engine))

    alembic_runner.migrate_up_to(_REVISION)

    assert "status" not in _column_names(alembic_engine)
    assert "disconnected_at" in _column_names(alembic_engine)
    assert _STATUS_ENUM not in _enum_names(alembic_engine)
    assert _CURRENT_INDEXES <= _index_names(alembic_engine)
    assert _PARENT_INDEXES.isdisjoint(_index_names(alembic_engine))

    alembic_runner.migrate_down_to(_PARENT_REVISION)

    assert "status" in _column_names(alembic_engine)
    assert "disconnected_at" in _column_names(alembic_engine)
    assert _STATUS_ENUM in _enum_names(alembic_engine)
    assert _PARENT_INDEXES <= _index_names(alembic_engine)
    assert _CURRENT_INDEXES.isdisjoint(_index_names(alembic_engine))
