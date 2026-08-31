"""Migration tests for event model-order removal."""

import pytest
import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

_PARENT_REVISION = "10fa347228db"
_REVISION = "629612c66084"
_FIRST_EVENT_ID = "00000000000000000000000000000001"
_SECOND_EVENT_ID = "00000000000000000000000000000002"


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
