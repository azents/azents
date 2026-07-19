"""AgentRun parent-result delivery migration tests."""

import importlib.util
import types
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from azcommon.testing.images import get_docker_hub_image
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_MIGRATION_PATH = (
    PROJECT_ROOT / "db-schemas/rdb/migrations/versions/"
    "a4d69bcc02e2_add_agent_run_parent_result_delivery.py"
)


def _load_migration() -> types.ModuleType:
    """Load the generated migration module from its revision file."""
    spec = importlib.util.spec_from_file_location(
        "agent_run_parent_result_delivery_migration",
        _MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("AgentRun parent-result migration could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parent_result_delivery_upgrade_and_downgrade(
    check_docker_availability: None,
) -> None:
    """Suppress historical subagent results and reverse the schema change."""
    del check_docker_availability
    migration = _load_migration()
    postgres_image = get_docker_hub_image("postgres:17")
    with PostgresContainer(postgres_image, driver="psycopg") as postgres:
        engine = sa.create_engine(postgres.get_connection_url())
        try:
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        CREATE TABLE session_agents (
                            id TEXT PRIMARY KEY,
                            agent_session_id TEXT NOT NULL UNIQUE,
                            kind TEXT NOT NULL,
                            parent_observed_run_index INTEGER,
                            parent_observed_event_id TEXT
                        )
                        """
                    )
                )
                connection.execute(
                    sa.text(
                        """
                        CREATE TABLE agent_runs (
                            id TEXT PRIMARY KEY,
                            session_id TEXT NOT NULL,
                            run_index INTEGER NOT NULL,
                            status TEXT NOT NULL,
                            terminal_result_event_id TEXT
                        )
                        """
                    )
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO session_agents (
                            id,
                            agent_session_id,
                            kind,
                            parent_observed_run_index,
                            parent_observed_event_id
                        )
                        VALUES
                            ('root-agent', 'root-session', 'root', NULL, NULL),
                            ('child-agent', 'child-session', 'subagent', NULL, NULL),
                            ('observed-agent', 'observed-session', 'subagent', 5,
                                'existing-event')
                        """
                    )
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO agent_runs (
                            id,
                            session_id,
                            run_index,
                            status,
                            terminal_result_event_id
                        )
                        VALUES
                            ('root-terminal', 'root-session', 1, 'completed',
                                'root-event'),
                            ('child-completed', 'child-session', 1, 'completed',
                                'child-event-1'),
                            ('child-failed', 'child-session', 2, 'failed',
                                'child-event-2'),
                            ('child-running', 'child-session', 3, 'running', NULL),
                            ('observed-terminal', 'observed-session', 1,
                                'interrupted', 'observed-event-1')
                        """
                    )
                )
                operations = Operations(MigrationContext.configure(connection))
                with patch.object(migration, "op", operations):
                    migration.upgrade()

                delivery_states = {
                    str(row["id"]): (
                        str(row["parent_result_delivery_state"])
                        if row["parent_result_delivery_state"] is not None
                        else None
                    )
                    for row in connection.execute(
                        sa.text(
                            """
                            SELECT id, parent_result_delivery_state::text
                                AS parent_result_delivery_state
                            FROM agent_runs
                            ORDER BY id
                            """
                        )
                    ).mappings()
                }
                assert delivery_states == {
                    "child-completed": "suppressed",
                    "child-failed": "suppressed",
                    "child-running": None,
                    "observed-terminal": "suppressed",
                    "root-terminal": None,
                }
                observed_rows = {
                    str(row["agent_session_id"]): (
                        row["parent_observed_run_index"],
                        row["parent_observed_event_id"],
                    )
                    for row in connection.execute(
                        sa.text(
                            """
                            SELECT
                                agent_session_id,
                                parent_observed_run_index,
                                parent_observed_event_id
                            FROM session_agents
                            ORDER BY agent_session_id
                            """
                        )
                    ).mappings()
                }
                assert observed_rows == {
                    "child-session": (2, "child-event-2"),
                    "observed-session": (5, "existing-event"),
                    "root-session": (None, None),
                }

                with patch.object(migration, "op", operations):
                    migration.downgrade()

                remaining_columns = {
                    str(name)
                    for name in connection.scalars(
                        sa.text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_name = 'agent_runs'
                            """
                        )
                    )
                }
                assert "parent_result_delivery_state" not in remaining_columns
                assert "parent_result_input_buffer_id" not in remaining_columns
                assert "parent_result_enqueued_at" not in remaining_columns
                enum_exists = connection.scalar(
                    sa.text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_type
                            WHERE typname =
                                'agent_run_parent_result_delivery_state'
                        )
                        """
                    )
                )
                assert enum_exists is False
        finally:
            engine.dispose()
