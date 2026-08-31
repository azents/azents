"""PostgreSQL migration tests for Channel Work awaiting input state."""

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command

from azents.rdb.channel_work_tracker_visibility_migration_test import (
    _insert_state,
    _migration_database,
    _seed_session,
    _states,
    _work_payload,
)

_PARENT_REVISION = "629612c66084"
_AWAITING_REVISION = "a66397c7eabc"


def _schema_three_payload(binding_id: str) -> dict[str, object]:
    """Build one valid pre-awaiting Channel Work payload."""
    return {
        **_work_payload(binding_id),
        "schema_version": 3,
        "tracker_visibility": "visible",
        "slack_presence_thread_ts": None,
        "slack_presence_initiator_user_id": None,
    }


def test_awaiting_input_migration_round_trips_channel_work_state(
    check_docker_availability: None,
) -> None:
    """Upgrade and downgrade add and remove only the nullable awaiting marker."""
    del check_docker_availability
    payload = _schema_three_payload("binding-awaiting")
    unrelated = {"schema_version": 3, "state": "scheduled"}

    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            _insert_state(
                connection,
                state_id="work-awaiting",
                namespace="external_channel",
                state_name="channel_work:binding-awaiting",
                state_json=payload,
                schema_version=3,
            )
            _insert_state(
                connection,
                state_id="unrelated-awaiting",
                namespace="external_channel",
                state_name="scheduled_task:binding-awaiting",
                state_json=unrelated,
                schema_version=3,
            )

        alembic_command.upgrade(config, _AWAITING_REVISION)
        with engine.connect() as connection:
            upgraded = _states(connection)

        assert upgraded["channel_work:binding-awaiting"] == {
            "schema_version": 4,
            "version": 8,
            "state_json": {
                **payload,
                "schema_version": 4,
                "awaiting_input_run_id": None,
            },
        }
        assert upgraded["scheduled_task:binding-awaiting"] == {
            "schema_version": 3,
            "version": 7,
            "state_json": unrelated,
        }

        alembic_command.downgrade(config, _PARENT_REVISION)
        with engine.connect() as connection:
            downgraded = _states(connection)

        assert downgraded["channel_work:binding-awaiting"] == {
            "schema_version": 3,
            "version": 9,
            "state_json": payload,
        }
        assert downgraded["scheduled_task:binding-awaiting"] == {
            "schema_version": 3,
            "version": 7,
            "state_json": unrelated,
        }


def test_awaiting_input_downgrade_requires_cleared_marker(
    check_docker_availability: None,
) -> None:
    """Older code cannot be restored while any Work is still awaiting input."""
    del check_docker_availability

    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            _insert_state(
                connection,
                state_id="work-awaiting-blocked",
                namespace="external_channel",
                state_name="channel_work:binding-awaiting-blocked",
                state_json=_schema_three_payload("binding-awaiting-blocked"),
                schema_version=3,
            )

        alembic_command.upgrade(config, _AWAITING_REVISION)
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE toolkit_states
                    SET state_json = jsonb_set(
                        state_json,
                        '{awaiting_input_run_id}',
                        '"run-1"'::jsonb
                    )
                    WHERE state_name = 'channel_work:binding-awaiting-blocked'
                    """
                )
            )

        with pytest.raises(RuntimeError, match="schema is inconsistent"):
            alembic_command.downgrade(config, _PARENT_REVISION)
