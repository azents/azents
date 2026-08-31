"""PostgreSQL migration tests for Slack Work presence ownership."""

import sqlalchemy as sa
from alembic import command as alembic_command

from azents.rdb.channel_work_tracker_visibility_migration_test import (
    _insert_state,
    _migration_database,
    _seed_session,
    _states,
    _work_payload,
)

_PARENT_REVISION = "2c2b5240fe20"
_PRESENCE_REVISION = "10fa347228db"


def test_slack_presence_migration_round_trips_channel_work_state(
    check_docker_availability: None,
) -> None:
    """Upgrade and downgrade preserve prior Work and add only nullable coordinates."""
    del check_docker_availability
    payload = {
        **_work_payload("binding-presence"),
        "schema_version": 2,
        "tracker_visibility": "hidden",
    }
    unrelated = {"schema_version": 2, "state": "scheduled"}

    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            _insert_state(
                connection,
                state_id="work-presence",
                namespace="external_channel",
                state_name="channel_work:binding-presence",
                state_json=payload,
                schema_version=2,
            )
            _insert_state(
                connection,
                state_id="unrelated-presence",
                namespace="external_channel",
                state_name="scheduled_task:binding-presence",
                state_json=unrelated,
                schema_version=2,
            )

        alembic_command.upgrade(config, _PRESENCE_REVISION)
        with engine.connect() as connection:
            upgraded = _states(connection)
            columns = {
                row["column_name"]
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'external_channel_connections'
                        """
                    )
                ).mappings()
            }

        assert upgraded["channel_work:binding-presence"] == {
            "schema_version": 3,
            "version": 8,
            "state_json": {
                **payload,
                "schema_version": 3,
                "slack_presence_thread_ts": None,
                "slack_presence_initiator_user_id": None,
            },
        }
        assert upgraded["scheduled_task:binding-presence"] == {
            "schema_version": 2,
            "version": 7,
            "state_json": unrelated,
        }
        assert {
            "slack_presence_lease_owner",
            "slack_presence_lease_until",
            "slack_presence_heartbeat_at",
        } <= columns

        alembic_command.downgrade(config, _PARENT_REVISION)
        with engine.connect() as connection:
            downgraded = _states(connection)
            remaining_columns = {
                row["column_name"]
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'external_channel_connections'
                        """
                    )
                ).mappings()
            }

        assert downgraded["channel_work:binding-presence"] == {
            "schema_version": 2,
            "version": 9,
            "state_json": payload,
        }
        assert downgraded["scheduled_task:binding-presence"] == {
            "schema_version": 2,
            "version": 7,
            "state_json": unrelated,
        }
        assert "slack_presence_lease_owner" not in remaining_columns
        assert "slack_presence_lease_until" not in remaining_columns
        assert "slack_presence_heartbeat_at" not in remaining_columns
