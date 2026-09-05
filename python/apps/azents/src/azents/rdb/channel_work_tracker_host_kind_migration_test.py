"""PostgreSQL migration tests for Channel Work Tracker host kind."""

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command

from azents.rdb.channel_work_awaiting_input_migration_test import (
    _schema_three_payload,
)
from azents.rdb.channel_work_tracker_visibility_migration_test import (
    _insert_state,
    _migration_database,
    _seed_session,
    _states,
)

_PARENT_REVISION = "7de5749cadd5"
_HOST_KIND_REVISION = "4ab7015e39b5"


def _schema_four_payload(binding_id: str) -> dict[str, object]:
    """Build one valid pre-host-kind Channel Work payload."""
    return {
        **_schema_three_payload(binding_id),
        "schema_version": 4,
        "awaiting_input_run_id": None,
        "projection_parts": [
            {
                "part_ordinal": 0,
                "desired_progress_revision": 2,
                "status": "present",
                "provider_message_key": "discord:111:555",
            }
        ],
    }


def test_tracker_host_kind_migration_round_trips_standalone_projection(
    check_docker_availability: None,
) -> None:
    """Upgrade classifies existing hosts and downgrade restores version four."""
    del check_docker_availability
    payload = _schema_four_payload("binding-host-kind")
    unrelated = {"schema_version": 4, "state": "scheduled"}

    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            _insert_state(
                connection,
                state_id="work-host-kind",
                namespace="external_channel",
                state_name="channel_work:binding-host-kind",
                state_json=payload,
                schema_version=4,
            )
            _insert_state(
                connection,
                state_id="unrelated-host-kind",
                namespace="external_channel",
                state_name="scheduled_task:binding-host-kind",
                state_json=unrelated,
                schema_version=4,
            )

        alembic_command.upgrade(config, _HOST_KIND_REVISION)
        with engine.connect() as connection:
            upgraded = _states(connection)

        projection_parts = payload["projection_parts"]
        assert isinstance(projection_parts, list)
        projection_part = projection_parts[0]
        assert isinstance(projection_part, dict)
        assert upgraded["channel_work:binding-host-kind"] == {
            "schema_version": 5,
            "version": 8,
            "state_json": {
                **payload,
                "schema_version": 5,
                "projection_parts": [
                    {
                        **projection_part,
                        "host_kind": "standalone",
                    }
                ],
            },
        }
        assert upgraded["scheduled_task:binding-host-kind"] == {
            "schema_version": 4,
            "version": 7,
            "state_json": unrelated,
        }

        alembic_command.downgrade(config, _PARENT_REVISION)
        with engine.connect() as connection:
            downgraded = _states(connection)

        assert downgraded["channel_work:binding-host-kind"] == {
            "schema_version": 4,
            "version": 9,
            "state_json": payload,
        }


def test_tracker_host_kind_downgrade_rejects_reply_host(
    check_docker_availability: None,
) -> None:
    """Older code cannot delete a conversational reply as a standalone Tracker."""
    del check_docker_availability

    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            _insert_state(
                connection,
                state_id="work-reply-host",
                namespace="external_channel",
                state_name="channel_work:binding-reply-host",
                state_json=_schema_four_payload("binding-reply-host"),
                schema_version=4,
            )

        alembic_command.upgrade(config, _HOST_KIND_REVISION)
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE toolkit_states
                    SET state_json = jsonb_set(
                        state_json,
                        '{projection_parts,0,host_kind}',
                        '"reply"'::jsonb
                    )
                    WHERE state_name = 'channel_work:binding-reply-host'
                    """
                )
            )

        with pytest.raises(RuntimeError, match="schema is inconsistent"):
            alembic_command.downgrade(config, _PARENT_REVISION)
