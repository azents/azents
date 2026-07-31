"""Migration tests for final legacy Runtime policy authority removal."""

import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT_REVISION = "a8e8788ca12d"
_REVISION = "aafb89c5904b"
_REMOVED_TABLES = {
    "agent_runtime_execution_settings",
    "agent_runtime_provider_overrides",
    "runtime_execution_policy_audit_events",
    "runtime_execution_profiles",
    "runtime_policy_snapshots",
    "workspace_runtime_execution_policies",
    "workspace_runtime_execution_profile_allowances",
}
_REMOVED_RUNTIME_COLUMNS = {
    "applied_runtime_policy_snapshot_id",
    "provider_config",
    "runtime_policy_snapshot_id",
}
_REMOVED_ENUMS = {
    "runtime_execution_audit_event_type",
    "runtime_execution_change_direction",
    "runtime_execution_management_layer",
    "runtime_execution_profile_lifecycle",
    "runtime_policy_snapshot_application_state",
}


def _enum_names(engine: Engine) -> set[str]:
    """Return enum type names in the migration test schema."""
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


def test_runtime_policy_authority_removal_has_exact_final_schema(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Remove only the replaced authority and retain recreation dispatch evidence."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)

    parent_inspector = sa.inspect(alembic_engine)
    assert _REMOVED_TABLES <= set(parent_inspector.get_table_names())
    assert _REMOVED_RUNTIME_COLUMNS <= {
        column["name"] for column in parent_inspector.get_columns("agent_runtimes")
    }
    assert _REMOVED_ENUMS <= _enum_names(alembic_engine)

    alembic_runner.migrate_up_to(_REVISION)

    final_inspector = sa.inspect(alembic_engine)
    assert _REMOVED_TABLES.isdisjoint(final_inspector.get_table_names())
    assert _REMOVED_RUNTIME_COLUMNS.isdisjoint(
        column["name"] for column in final_inspector.get_columns("agent_runtimes")
    )
    assert _REMOVED_ENUMS.isdisjoint(_enum_names(alembic_engine))
    assert "dispatched_generation" in {
        column["name"]
        for column in final_inspector.get_columns("runtime_recreation_operation_items")
    }

    alembic_runner.migrate_down_to(_PARENT_REVISION)

    restored_inspector = sa.inspect(alembic_engine)
    assert _REMOVED_TABLES <= set(restored_inspector.get_table_names())
    assert _REMOVED_RUNTIME_COLUMNS <= {
        column["name"] for column in restored_inspector.get_columns("agent_runtimes")
    }
    assert _REMOVED_ENUMS <= _enum_names(alembic_engine)
    assert "dispatched_generation" not in {
        column["name"]
        for column in restored_inspector.get_columns(
            "runtime_recreation_operation_items"
        )
    }
