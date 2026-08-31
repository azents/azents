"""Migration tests for event model-order removal."""

from concurrent.futures import Future, ThreadPoolExecutor
from time import monotonic, sleep

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "10fa347228db"
_REVISION = "629612c66084"
_FIRST_EVENT_ID = "00000000000000000000000000000001"
_SECOND_EVENT_ID = "00000000000000000000000000000002"
_MIGRATION_APPLICATION_NAME = "event_model_order_removal_test"
_LOCK_WAIT_TIMEOUT_SECONDS = 10.0


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    """Return reflected column names for one table."""
    return {column["name"] for column in inspector.get_columns(table_name)}


def _seed_base_rows(connection: sa.Connection) -> None:
    """Seed the minimum Workspace, Agent, and Session rows."""
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('event-order-workspace', 'Event Order', 'event-order')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id, workspace_id, name, model_selection,
                lightweight_model_selection, selectable_model_options,
                main_model_label, lightweight_model_label
            )
            VALUES (
                'event-order-agent', 'event-order-workspace', 'Event Order Agent',
                '{}'::jsonb, '{}'::jsonb,
                '[{"label":"default","model_selection":{}}]'::jsonb,
                'default', 'default'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status, start_reason,
                session_kind, product_mode, run_state
            )
            VALUES (
                'event-order-session', 'event-order-workspace',
                'event-order-agent', 'event-order-session',
                'active', 'initial', 'root', 'team', 'idle'
            )
            """
        )
    )


def _insert_event(
    connection: sa.Connection,
    *,
    event_id: str,
    model_order: int,
) -> None:
    """Insert one legacy event."""
    connection.execute(
        sa.text(
            """
            INSERT INTO events (
                id, session_id, kind, payload, model_order
            )
            VALUES (
                :event_id, 'event-order-session', 'user_message',
                jsonb_build_object('sender_user_id', NULL, 'content', 'test'),
                :model_order
            )
            """
        ),
        {"event_id": event_id, "model_order": model_order},
    )


def _migration_config(database_url: str) -> AlembicConfig:
    """Build an Alembic config with an identifiable migration connection."""
    url = sa.make_url(database_url).update_query_dict(
        {"application_name": _MIGRATION_APPLICATION_NAME}
    )
    config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    return config


def _wait_until_migration_is_blocked(
    engine: Engine,
    migration_future: Future[None],
) -> None:
    """Wait until PostgreSQL reports the migration waiting on its table lock."""
    deadline = monotonic() + _LOCK_WAIT_TIMEOUT_SECONDS
    while monotonic() < deadline:
        if migration_future.done():
            try:
                migration_future.result()
            except Exception as error:
                raise AssertionError(
                    "Migration completed before waiting on the writer lock."
                ) from error
            raise AssertionError(
                "Migration completed before waiting on the writer lock."
            )

        with engine.connect() as connection:
            activity = (
                connection.execute(
                    sa.text(
                        """
                        SELECT wait_event_type, query
                        FROM pg_stat_activity
                        WHERE application_name = :application_name
                        ORDER BY backend_start DESC
                        LIMIT 1
                        """
                    ),
                    {"application_name": _MIGRATION_APPLICATION_NAME},
                )
                .mappings()
                .one_or_none()
            )
        if (
            activity is not None
            and activity["wait_event_type"] == "Lock"
            and "LOCK TABLE agent_sessions, events" in activity["query"]
        ):
            return
        sleep(0.01)

    raise AssertionError("Migration did not wait on the legacy writer lock.")


def test_event_model_order_is_removed_and_downgrade_reconstructs_id_order(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Upgrade removes order state while downgrade rebuilds it from event IDs."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_base_rows(connection)
        _insert_event(connection, event_id=_FIRST_EVENT_ID, model_order=1000)
        _insert_event(connection, event_id=_SECOND_EVENT_ID, model_order=2000)
        connection.execute(
            sa.text(
                """
                UPDATE agent_sessions
                SET model_input_head_event_id = :head_event_id,
                    model_input_head_model_order = 2000,
                    model_file_gc_cursor_event_id = :cursor_event_id,
                    model_file_gc_cursor_model_order = 1000
                WHERE id = 'event-order-session'
                """
            ),
            {
                "head_event_id": _SECOND_EVENT_ID,
                "cursor_event_id": _FIRST_EVENT_ID,
            },
        )

    alembic_runner.migrate_up_to(_REVISION)

    with alembic_engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert "model_order" not in _column_names(inspector, "events")
        session_columns = _column_names(inspector, "agent_sessions")
        assert "model_input_head_model_order" not in session_columns
        assert "model_file_gc_cursor_model_order" not in session_columns
        session_indexes = {
            index["name"] for index in inspector.get_indexes("agent_sessions")
        }
        assert "ix_agent_sessions_model_file_gc_cursor" in session_indexes
        assert "ix_agent_sessions_model_file_gc_lag" not in session_indexes
        row = connection.execute(
            sa.text(
                """
                SELECT model_input_head_event_id, model_file_gc_cursor_event_id
                FROM agent_sessions
                WHERE id = 'event-order-session'
                """
            )
        ).one()
        assert row == (_SECOND_EVENT_ID, _FIRST_EVENT_ID)

    alembic_runner.migrate_down_to(_PARENT_REVISION)

    with alembic_engine.connect() as connection:
        session_indexes = {
            index["name"]
            for index in sa.inspect(connection).get_indexes("agent_sessions")
        }
        assert "ix_agent_sessions_model_file_gc_cursor" not in session_indexes
        assert "ix_agent_sessions_model_file_gc_lag" in session_indexes
        event_orders = connection.execute(
            sa.text("SELECT id, model_order FROM events ORDER BY id")
        ).all()
        assert event_orders == [
            (_FIRST_EVENT_ID, 1000),
            (_SECOND_EVENT_ID, 2000),
        ]
        session_orders = connection.execute(
            sa.text(
                """
                SELECT model_input_head_model_order,
                       model_file_gc_cursor_model_order
                FROM agent_sessions
                WHERE id = 'event-order-session'
                """
            )
        ).one()
        assert session_orders == (2000, 1000)


def test_event_model_order_removal_rejects_unrepresentable_current_head(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Upgrade fails when ID order would hide a logically later event."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_base_rows(connection)
        _insert_event(connection, event_id=_FIRST_EVENT_ID, model_order=2000)
        _insert_event(connection, event_id=_SECOND_EVENT_ID, model_order=1000)
        connection.execute(
            sa.text(
                """
                UPDATE agent_sessions
                SET model_input_head_event_id = :head_event_id,
                    model_input_head_model_order = 1000
                WHERE id = 'event-order-session'
                """
            ),
            {"head_event_id": _SECOND_EVENT_ID},
        )

    with pytest.raises(DBAPIError, match="cannot be represented by event ID order"):
        alembic_runner.migrate_up_to(_REVISION)


def test_event_model_order_removal_blocks_writers_before_preflight(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
    migration_database_url: str,
) -> None:
    """Upgrade takes write-blocking locks before validating ID compatibility."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_base_rows(connection)
        _insert_event(connection, event_id=_FIRST_EVENT_ID, model_order=2000)
        _insert_event(connection, event_id=_SECOND_EVENT_ID, model_order=1000)
        connection.execute(
            sa.text(
                """
                UPDATE agent_sessions
                SET model_input_head_event_id = :head_event_id,
                    model_input_head_model_order = 1000
                WHERE id = 'event-order-session'
                """
            ),
            {"head_event_id": _SECOND_EVENT_ID},
        )

    config = _migration_config(migration_database_url)
    with alembic_engine.connect() as writer:
        writer_transaction = writer.begin()
        writer.execute(
            sa.text(
                """
                UPDATE agent_sessions
                SET status = status
                WHERE id = 'event-order-session'
                """
            )
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            migration_future = executor.submit(
                alembic_command.upgrade,
                config,
                _REVISION,
            )
            try:
                _wait_until_migration_is_blocked(
                    alembic_engine,
                    migration_future,
                )
            finally:
                writer_transaction.rollback()

            with pytest.raises(
                DBAPIError,
                match="cannot be represented by event ID order",
            ):
                migration_future.result(timeout=_LOCK_WAIT_TIMEOUT_SECONDS)
