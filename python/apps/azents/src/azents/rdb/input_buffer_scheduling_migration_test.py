"""InputBuffer scheduling mode migration tests."""

import importlib.util
import json
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
    "b96607c4c3db_add_input_buffer_scheduling_mode.py"
)


def _load_migration() -> types.ModuleType:
    """Load the generated migration module from its revision file."""
    spec = importlib.util.spec_from_file_location(
        "input_buffer_scheduling_migration",
        _MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("InputBuffer scheduling migration could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_input_buffer_scheduling_upgrade_and_downgrade(
    check_docker_availability: None,
) -> None:
    """Backfill source-owned scheduling intent and reverse the schema change."""
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
                        CREATE TYPE input_buffer_kind AS ENUM (
                            'user_message',
                            'goal_continuation',
                            'action_message',
                            'agent_message'
                        )
                        """
                    )
                )
                connection.execute(
                    sa.text(
                        """
                        CREATE TABLE input_buffers (
                            id TEXT PRIMARY KEY,
                            session_id TEXT NOT NULL,
                            kind input_buffer_kind NOT NULL,
                            metadata JSONB NOT NULL
                        )
                        """
                    )
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO input_buffers (id, session_id, kind, metadata)
                        VALUES
                            ('user', 'session-1', 'user_message',
                                CAST(:user_metadata AS JSONB)),
                            ('send', 'session-1', 'agent_message',
                                CAST(:send_metadata AS JSONB)),
                            ('followup', 'session-1', 'agent_message',
                                CAST(:followup_metadata AS JSONB))
                        """
                    ),
                    {
                        "user_metadata": json.dumps({"source": "chat"}),
                        "send_metadata": json.dumps(
                            {
                                "source": "agent_mailbox",
                                "message_kind": "send_message",
                            }
                        ),
                        "followup_metadata": json.dumps(
                            {
                                "source": "agent_mailbox",
                                "message_kind": "followup_task",
                            }
                        ),
                    },
                )
                operations = Operations(MigrationContext.configure(connection))
                with patch.object(migration, "op", operations):
                    migration.upgrade()

                scheduling_mode_rows = connection.execute(
                    sa.text(
                        """
                        SELECT id, scheduling_mode::text AS scheduling_mode
                        FROM input_buffers
                        ORDER BY id
                        """
                    )
                ).mappings()
                scheduling_modes = {
                    str(row["id"]): str(row["scheduling_mode"])
                    for row in scheduling_mode_rows
                }
                assert scheduling_modes == {
                    "followup": "wake_session",
                    "send": "queue_only",
                    "user": "wake_session",
                }
                nullable = connection.scalar(
                    sa.text(
                        """
                        SELECT is_nullable
                        FROM information_schema.columns
                        WHERE table_name = 'input_buffers'
                            AND column_name = 'scheduling_mode'
                        """
                    )
                )
                assert nullable == "NO"
                index_exists = connection.scalar(
                    sa.text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_indexes
                            WHERE tablename = 'input_buffers'
                                AND indexname =
                                    'ix_input_buffers_session_id_scheduling_mode'
                        )
                        """
                    )
                )
                assert index_exists is True

                with patch.object(migration, "op", operations):
                    migration.downgrade()

                column_exists = connection.scalar(
                    sa.text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name = 'input_buffers'
                                AND column_name = 'scheduling_mode'
                        )
                        """
                    )
                )
                enum_exists = connection.scalar(
                    sa.text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_type
                            WHERE typname = 'input_buffer_scheduling_mode'
                        )
                        """
                    )
                )
                assert column_exists is False
                assert enum_exists is False
        finally:
            engine.dispose()
