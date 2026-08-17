"""Scheduled Task ORM model tests."""

from typing import cast

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from testcontainers.postgres import PostgresContainer

from azents.core.enums import ScheduledTaskScheduleType
from azents.rdb.models.scheduled_task import (
    RDBScheduledTask,
    scheduled_task_schedule_type_enum,
)


class TestRDBScheduledTask:
    """Scheduled Task schema contract tests."""

    def test_schedule_enum_is_postgresql_owned(self) -> None:
        """The migration owns the enum type while the model references it."""
        assert scheduled_task_schedule_type_enum.name == (
            "scheduled_task_schedule_type"
        )
        assert scheduled_task_schedule_type_enum.create_type is False
        assert scheduled_task_schedule_type_enum.values_callable is not None
        assert [value.value for value in ScheduledTaskScheduleType] == ["once", "cron"]

    def test_m1_columns_and_foreign_keys_are_present(self) -> None:
        """The model exposes the exact Task ownership and cursor columns."""
        table = cast(sa.Table, RDBScheduledTask.__table__)
        columns = table.c

        assert set(columns.keys()) == {
            "id",
            "workspace_id",
            "agent_id",
            "session_id",
            "binding_id",
            "title",
            "objective",
            "schedule_type",
            "scheduled_at",
            "cron_expression",
            "timezone",
            "next_eligible_at",
            "active_cycle_id",
            "active_scheduled_for",
            "pending_scheduled_for",
            "lease_owner",
            "lease_until",
            "created_at",
            "updated_at",
        }
        assert columns.workspace_id.nullable is False
        assert columns.agent_id.nullable is False
        assert columns.session_id.nullable is False
        assert columns.binding_id.nullable is True
        assert str(columns.id.type) == "VARCHAR(32)"

        foreign_keys = {
            constraint.name: (
                str(constraint.elements[0].target_fullname),
                constraint.ondelete,
            )
            for constraint in table.foreign_key_constraints
        }
        assert foreign_keys == {
            "fk_scheduled_tasks_workspace_id": ("workspaces.id", "RESTRICT"),
            "fk_scheduled_tasks_agent_id": ("agents.id", "RESTRICT"),
            "fk_scheduled_tasks_session_id": ("agent_sessions.id", "RESTRICT"),
            "fk_scheduled_tasks_binding_id": (
                "external_channel_bindings.id",
                "RESTRICT",
            ),
        }

    def test_named_m1_constraints_and_indexes_are_registered(self) -> None:
        """Schedule, cycle, pending, and bounded-scan contracts are named."""
        table = cast(sa.Table, RDBScheduledTask.__table__)
        constraints = {constraint.name for constraint in table.constraints}
        assert {
            "ck_scheduled_tasks_schedule_shape",
            "ck_scheduled_tasks_active_cycle_fence",
            "ck_scheduled_tasks_pending_occurrence",
        } <= constraints

        indexes = {index.name for index in table.indexes}
        assert indexes == {
            "ix_scheduled_tasks_next_eligible_at_id",
            "ix_scheduled_tasks_session_id",
            "ix_scheduled_tasks_binding_id",
            "ix_scheduled_tasks_active_cycle_id",
        }


def _seed_constraint_identity(connection: sa.Connection) -> None:
    """Seed the minimum ownership graph required by Scheduled Task FKs."""
    connection.execute(
        text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES (
                'scheduled-task-constraint-ws0000',
                'Scheduled Task Constraint Workspace',
                'scheduled-task-constraint'
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO agents (
                id, workspace_id, name, model_selection,
                lightweight_model_selection, selectable_model_options,
                main_model_label, lightweight_model_label
            )
            VALUES (
                'scheduled-task-constraint-ag0000',
                'scheduled-task-constraint-ws0000',
                'Scheduled Task Constraint Agent',
                '{}'::jsonb,
                '{}'::jsonb,
                '[{"label":"default","model_selection":{}}]'::jsonb,
                'default',
                'default'
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status,
                start_reason, session_kind, product_mode
            )
            VALUES (
                'scheduled-task-constraint-se0000',
                'scheduled-task-constraint-ws0000',
                'scheduled-task-constraint-ag0000',
                'scheduled-task-constraint-se0000',
                'active',
                'initial',
                'root',
                'team'
            )
            """
        )
    )


_SCHEDULED_TASK_INSERT = text(
    """
    INSERT INTO scheduled_tasks (
        id, workspace_id, agent_id, session_id, title, objective,
        schedule_type, next_eligible_at, scheduled_at, cron_expression, timezone,
        active_cycle_id, active_scheduled_for, pending_scheduled_for
    )
    VALUES (
        :id, :workspace_id, :agent_id, :session_id, 'Constraint test',
        'Validate database constraints.', :schedule_type,
        '2026-01-01T00:00:00+00:00', :scheduled_at, :cron_expression, :timezone,
        :active_cycle_id, :active_scheduled_for, :pending_scheduled_for
    )
    """
)


def _assert_scheduled_task_insert_rejected(
    connection: sa.Connection,
    values: dict[str, object],
) -> None:
    """Assert one invalid Scheduled Task row is rejected by PostgreSQL."""
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(_SCHEDULED_TASK_INSERT, values)


def test_installed_schema_enforces_scheduled_task_cursor_constraints(
    latest_db_schema: None,
    postgres_container: PostgresContainer,
) -> None:
    """The installed schema rejects invalid schedule and cursor combinations."""
    engine = create_engine(postgres_container.get_connection_url())
    connection = engine.connect()
    transaction = connection.begin()
    try:
        _seed_constraint_identity(connection)
        base_values: dict[str, object] = {
            "workspace_id": "scheduled-task-constraint-ws0000",
            "agent_id": "scheduled-task-constraint-ag0000",
            "session_id": "scheduled-task-constraint-se0000",
            "schedule_type": "once",
            "scheduled_at": "2026-01-01T00:00:00+00:00",
            "cron_expression": None,
            "timezone": None,
            "active_cycle_id": None,
            "active_scheduled_for": None,
            "pending_scheduled_for": None,
        }

        _assert_scheduled_task_insert_rejected(
            connection,
            {
                **base_values,
                "id": "scheduled-task-constraint-on0000",
                "scheduled_at": None,
            },
        )
        _assert_scheduled_task_insert_rejected(
            connection,
            {
                **base_values,
                "id": "scheduled-task-constraint-cy0000",
                "active_cycle_id": "scheduled-task-cycle",
            },
        )
        _assert_scheduled_task_insert_rejected(
            connection,
            {
                **base_values,
                "id": "scheduled-task-constraint-pe0000",
                "active_cycle_id": "scheduled-task-cycle",
                "active_scheduled_for": "2026-01-01T00:00:00+00:00",
                "pending_scheduled_for": "2026-01-01T00:00:00+00:00",
            },
        )
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()
