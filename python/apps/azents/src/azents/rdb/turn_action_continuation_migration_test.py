"""Migration coverage for the hidden TurnAction continuation mailbox kind."""

import json
from collections.abc import Generator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "3d9280a9ce92"
_CONTINUATION_REVISION = "0a534149c228"
_SESSION_ID = "1" * 32
_EXISTING_ROW_ID = "2" * 32
_CONTINUATION_ROW_ID = "3" * 32


@contextmanager
def _migration_database() -> Generator[tuple[AlembicConfig, sa.Engine]]:
    """Create an isolated PostgreSQL database for migration verification."""
    with PostgresContainer("postgres:17", driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        engine = sa.create_engine(url)
        try:
            yield config, engine
        finally:
            engine.dispose()


def _set_replication_role(
    connection: sa.Connection,
    role: str,
) -> None:
    """Set test-only FK enforcement mode for isolated fixture rows."""
    connection.execute(sa.text(f"SET session_replication_role = {role}"))


def test_turn_action_continuation_enum_preserves_existing_mailbox_rows(
    check_docker_availability: None,
) -> None:
    """Upgrade adds the hidden kind without changing existing persisted rows."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _set_replication_role(connection, "replica")
            connection.execute(
                sa.text(
                    """
                    INSERT INTO mailbox_items (
                        id, session_id, kind, scheduling_mode,
                        requested_model_target_label, requested_reasoning_effort,
                        sender_user_id, idempotency_key, order_group, order_sequence,
                        payload
                    )
                    VALUES (
                        :id,
                        :session_id,
                        'action_message',
                        'wake_session',
                        NULL,
                        NULL,
                        NULL,
                        'existing-action',
                        :id,
                        0,
                        '{"type":"action_message","items":[{"item_key":"action_message:0","presentation_kind":"action_message","content":"","metadata":{},"action":{"type":"goal"},"attachments":[],"file_parts":[]}]}'::jsonb
                    )
                    """
                ),
                {"id": _EXISTING_ROW_ID, "session_id": _SESSION_ID},
            )
            _set_replication_role(connection, "origin")

        alembic_command.upgrade(config, _CONTINUATION_REVISION)
        with engine.begin() as connection:
            existing = (
                connection.execute(
                    sa.text(
                        """
                    SELECT kind::text AS kind, payload
                    FROM mailbox_items
                    WHERE id = :id
                    """
                    ),
                    {"id": _EXISTING_ROW_ID},
                )
                .mappings()
                .one()
            )
            assert existing["kind"] == "action_message"
            assert existing["payload"]["type"] == "action_message"

            _set_replication_role(connection, "replica")
            continuation_payload = {
                "type": "turn_action_continuation",
                "items": [
                    {
                        "item_key": "turn_action_continuation:0",
                        "presentation_kind": "turn_action_continuation",
                    }
                ],
                "bridge_identity": "bridge-001",
                "action_execution_id": "execution-001",
                "originating_run_id": "run-001",
                "predecessor_run_id": "run-001",
                "terminal_status": "completed",
                "reason_code": None,
                "failure_summary": None,
                "cancellation_summary": None,
                "result": {
                    "type": "agent_create_git_worktree",
                    "source_project_path": "/workspace/agent/repo",
                    "generated_worktree_path": "/workspace/agent/worktree",
                    "requested_starting_ref": None,
                    "resolved_base_commit": None,
                    "branch_name": "agent/worktree",
                },
            }
            connection.execute(
                sa.text(
                    """
                    INSERT INTO mailbox_items (
                        id, session_id, kind, scheduling_mode,
                        requested_model_target_label, requested_reasoning_effort,
                        sender_user_id, idempotency_key, order_group, order_sequence,
                        payload
                    )
                    VALUES (
                        :id,
                        :session_id,
                        'turn_action_continuation',
                        'wake_session',
                        NULL,
                        NULL,
                        NULL,
                        'turn_action_continuation:execution-001',
                        :id,
                        0,
                        CAST(:payload AS jsonb)
                    )
                    """
                ),
                {
                    "id": _CONTINUATION_ROW_ID,
                    "session_id": _SESSION_ID,
                    "payload": json.dumps(continuation_payload),
                },
            )
            _set_replication_role(connection, "origin")

        alembic_command.downgrade(config, _PARENT_REVISION)
        alembic_command.upgrade(config, _CONTINUATION_REVISION)
        with engine.connect() as connection:
            rows = (
                connection.execute(
                    sa.text(
                        """
                    SELECT id, kind::text AS kind
                    FROM mailbox_items
                    ORDER BY id
                    """
                    )
                )
                .mappings()
                .all()
            )
        assert rows == [
            {"id": _EXISTING_ROW_ID, "kind": "action_message"},
            {
                "id": _CONTINUATION_ROW_ID,
                "kind": "turn_action_continuation",
            },
        ]
