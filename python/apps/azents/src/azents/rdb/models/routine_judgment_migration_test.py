"""Real PostgreSQL judgment enum migration and retained payload round trip."""

import json

import sqlalchemy as sa
from alembic import command
from azcommon.uuid import uuid7
from testcontainers.postgres import PostgresContainer

from azents.core.enums import EventKind
from azents.engine.events.routine_judgment_test import _observation
from azents.engine.events.types import validate_event_payload
from azents.rdb.models.routine_migration_test import _seed_legacy
from azents.testing.migration_database import isolated_migration_database


def test_judgment_migration_retains_observation_without_a_run(
    postgres_container: PostgresContainer,
) -> None:
    with isolated_migration_database(postgres_container, template=None) as database:
        command.upgrade(database.config, "08a588456917")
        legacy = _seed_legacy(database.engine, binding_count=0)
        with database.engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_enum e JOIN pg_type t "
                        "ON t.oid=e.enumtypid WHERE t.typname='event_kind' "
                        "AND e.enumlabel='routine_judgment'"
                    )
                )
                == 0
            )
        command.upgrade(database.config, "854782c43687")
        observation = _observation()
        with database.engine.begin() as connection:
            assert connection.scalar(
                sa.text("SELECT enum_range(NULL::event_kind)::text[]")
            ) == [kind.value for kind in EventKind]
            connection.execute(
                sa.text(
                    "INSERT INTO events(id,session_id,kind,payload,provider,model) "
                    "VALUES (:id,:session,'routine_judgment',CAST(:payload AS jsonb),"
                    "'openai','synthetic-model')"
                ),
                {
                    "id": uuid7().hex,
                    "session": legacy.session_id,
                    "payload": observation.payload.model_dump_json(),
                },
            )
            stored = connection.execute(
                sa.text("SELECT kind,payload,provider,model FROM events")
            ).one()
            assert stored.kind == EventKind.ROUTINE_JUDGMENT.value
            assert (
                validate_event_payload(
                    EventKind.ROUTINE_JUDGMENT, json.loads(json.dumps(stored.payload))
                )
                == observation.payload
            )
            assert stored.provider == "openai"
            assert stored.model == "synthetic-model"
            assert connection.scalar(sa.text("SELECT count(*) FROM agent_runs")) == 0
            assert connection.scalar(
                sa.text("SELECT version_num FROM alembic_version")
            ) == ("854782c43687")
