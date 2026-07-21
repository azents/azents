"""Latest session system prompt snapshot migration tests."""

import datetime
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
    "6412e7bf0530_store_latest_session_system_prompt.py"
)


def _load_migration() -> types.ModuleType:
    """Load the generated migration module from its revision file."""
    spec = importlib.util.spec_from_file_location(
        "session_system_prompt_snapshot_migration",
        _MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("System prompt snapshot migration could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_session_system_prompt_snapshot_migration(
    check_docker_availability: None,
) -> None:
    """Keep the newest prompt per session and remove event duplicates."""
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
                        CREATE TABLE agent_sessions (
                            id TEXT PRIMARY KEY
                        )
                        """
                    )
                )
                connection.execute(
                    sa.text(
                        """
                        CREATE TABLE events (
                            id TEXT PRIMARY KEY,
                            session_id TEXT NOT NULL REFERENCES agent_sessions(id),
                            kind TEXT NOT NULL,
                            payload JSONB NOT NULL,
                            model_order BIGINT NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL
                        )
                        """
                    )
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO agent_sessions (id)
                        VALUES ('session-1'), ('session-2')
                        """
                    )
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO events (
                            id,
                            session_id,
                            kind,
                            payload,
                            model_order,
                            created_at
                        )
                        VALUES
                            (
                                'event-1',
                                'session-1',
                                'turn_marker',
                                CAST(:old_prompt AS JSONB),
                                1000,
                                :created_at
                            ),
                            (
                                'event-2',
                                'session-1',
                                'turn_marker',
                                CAST(:new_prompt AS JSONB),
                                2000,
                                :created_at
                            ),
                            (
                                'event-3',
                                'session-2',
                                'turn_marker',
                                CAST(:usage_only AS JSONB),
                                1000,
                                :created_at
                            )
                        """
                    ),
                    {
                        "old_prompt": json.dumps(
                            {
                                "run_id": "run-1",
                                "system_prompt": {"final_prompt": {"content": "old"}},
                            }
                        ),
                        "new_prompt": json.dumps(
                            {
                                "run_id": "run-2",
                                "system_prompt": {"final_prompt": {"content": "new"}},
                            }
                        ),
                        "usage_only": json.dumps({"run_id": "run-3"}),
                        "created_at": datetime.datetime.now(datetime.UTC),
                    },
                )

                operations = Operations(MigrationContext.configure(connection))
                with patch.object(migration, "op", operations):
                    migration.upgrade()

                snapshots = connection.execute(
                    sa.text(
                        """
                        SELECT session_id, system_prompt
                        FROM agent_session_system_prompt_snapshots
                        ORDER BY session_id
                        """
                    )
                ).mappings()
                assert [dict(row) for row in snapshots] == [
                    {
                        "session_id": "session-1",
                        "system_prompt": {"final_prompt": {"content": "new"}},
                    }
                ]

                payloads = connection.execute(
                    sa.text("SELECT payload FROM events ORDER BY id")
                ).scalars()
                assert all("system_prompt" not in payload for payload in payloads)

                with patch.object(migration, "op", operations):
                    migration.downgrade()
                table = connection.execute(
                    sa.text(
                        """
                        SELECT to_regclass(
                            'agent_session_system_prompt_snapshots'
                        )
                        """
                    )
                ).scalar_one()
                assert table is None
        finally:
            engine.dispose()
