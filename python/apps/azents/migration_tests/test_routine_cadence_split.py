"""Existing tick choices become minimum delay before new tick defaults apply."""

import pytest
import sqlalchemy as sa
from pytest_alembic import MigrationContext
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


def test_routine_cadence_transfer_and_defaults(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Preserve old choices, normalize the floor and enforce the complete pair."""
    alembic_runner.migrate_up_to("f18bc3d0bf09")
    ticks = [1, 29, 30, 60, 180, 240, 1440]
    insert = sa.text("""
        INSERT INTO agents (
            id, workspace_id, name, model_selection, lightweight_model_selection,
            selectable_model_options, main_model_label, lightweight_model_label,
            enabled, type, memory_enabled, routine_check_interval_minutes
        ) VALUES (
            :id, 'cadence-workspace', 'Cadence migration', '{}', '{}',
            '[{"candidates":[{}]}]', 'default', 'lightweight',
            true, 'public', true, :tick
        )
    """)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO workspaces(id,name,handle) "
                "VALUES ('cadence-workspace','Cadence','cadence-migration')"
            )
        )
        for tick in ticks:
            connection.execute(insert, {"id": f"cadence-{tick}", "tick": tick})
    alembic_runner.migrate_up_to("e67a51c3c652")
    with alembic_engine.begin() as connection:
        for tick in ticks:
            row = connection.execute(
                sa.text(
                    "SELECT routine_min_action_delay_minutes, "
                    "routine_check_interval_minutes "
                    "FROM agents WHERE id=:id"
                ),
                {"id": f"cadence-{tick}"},
            ).one()
            assert row == (max(tick, 30), max(tick, 180))
        connection.execute(
            sa.text("""
            INSERT INTO agents (
                id, workspace_id, name, model_selection, lightweight_model_selection,
                selectable_model_options, main_model_label, lightweight_model_label,
                enabled, type, memory_enabled
            ) VALUES (
                'cadence-default', 'cadence-workspace', 'Default', '{}', '{}',
                '[{"candidates":[{}]}]', 'default', 'lightweight', true, 'public', true
            )
        """)
        )
        assert connection.execute(
            sa.text(
                "SELECT routine_min_action_delay_minutes, "
                "routine_check_interval_minutes "
                "FROM agents WHERE id='cadence-default'"
            )
        ).one() == (30, 180)
    for minimum, tick in [(29, 180), (60, 30), (1441, 1441)]:
        with pytest.raises(IntegrityError), alembic_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE agents SET routine_min_action_delay_minutes=:minimum, "
                    "routine_check_interval_minutes=:tick WHERE id='cadence-default'"
                ),
                {"minimum": minimum, "tick": tick},
            )
    alembic_runner.migrate_down_to("f18bc3d0bf09")
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text(
                    "SELECT routine_check_interval_minutes "
                    "FROM agents WHERE id='cadence-60'"
                )
            )
            == 180
        )
