"""Preserve reporting obligations and history while migrating quiet completion."""

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine

from azents.consts import PROJECT_ROOT


def test_existing_tasks_cycles_and_results_remain_report_required(
    alembic_engine: Engine,
) -> None:
    directory = ScriptDirectory.from_config(
        Config(PROJECT_ROOT / "db-schemas/rdb/alembic.ini")
    )
    revision = directory.get_revision("2a9be235de5d")
    assert revision is not None
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text("CREATE TABLE scheduled_tasks (id text PRIMARY KEY)")
        )
        connection.execute(sa.text("INSERT INTO scheduled_tasks VALUES ('task')"))
        connection.execute(
            sa.text("""
            CREATE TABLE toolkit_states (
                toolkit_namespace text, state_name text, state_json jsonb
            )
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO toolkit_states VALUES
            ('scheduled', 'cycle:active', jsonb_build_object(
                'objective', 'Keep checking', 'progress_title', 'Checking',
                'tracker_desired_revision', 1)),
            ('scheduled', 'cycle:admitted', jsonb_build_object(
                'progress_title', null, 'tracker_desired_revision', 0)),
            ('other', 'cycle:other', '{}'::jsonb)
        """)
        )
        connection.execute(sa.text("CREATE TABLE events (kind text, payload jsonb)"))
        connection.execute(
            sa.text("""
            INSERT INTO events VALUES ('scheduled_task_result',
                jsonb_build_object('result', 'Done', 'status', 'finished')),
                ('assistant_message', '{}'::jsonb)
        """)
        )
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.upgrade()
        assert (
            connection.scalar(sa.text("SELECT allow_silent FROM scheduled_tasks"))
            is False
        )
        rows = connection.execute(
            sa.text("""
            SELECT state_name, state_json FROM toolkit_states ORDER BY state_name
        """)
        ).all()
        assert rows[0][1] == {
            "objective": "Keep checking",
            "progress_title": "Checking",
            "tracker_desired_revision": 1,
            "allow_silent": False,
            "progress_reported": True,
        }
        assert rows[1][1]["allow_silent"] is False
        assert rows[1][1]["progress_reported"] is False
        assert rows[2][1] == {}
        result = connection.scalar(
            sa.text("""
            SELECT payload FROM events WHERE kind = 'scheduled_task_result'
        """)
        )
        assert result == {
            "result": "Done",
            "status": "finished",
            "notify": True,
            "suppression_reason": None,
        }
        assert (
            connection.scalar(
                sa.text("""
            SELECT payload FROM events WHERE kind = 'assistant_message'
        """)
            )
            == {}
        )
        connection.execute(
            sa.text("""
            UPDATE events
            SET payload = payload || jsonb_build_object(
                'notify', false, 'suppression_reason', 'No changes found'
            ) WHERE kind = 'scheduled_task_result'
        """)
        )
        quiet_result = {
            **result,
            "notify": False,
            "suppression_reason": "No changes found",
        }
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.downgrade()
        assert (
            connection.scalar(
                sa.text("""
            SELECT payload FROM events WHERE kind = 'scheduled_task_result'
        """)
            )
            == quiet_result
        )
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.upgrade()
        retained = connection.scalar(
            sa.text("""
            SELECT payload FROM events WHERE kind = 'scheduled_task_result'
        """)
        )
        assert retained["notify"] is False
        assert retained["suppression_reason"] == "No changes found"
