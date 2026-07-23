"""Migration tests for provider-native Channel Work progress."""

import json
from collections.abc import Generator, Mapping, Sequence

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from azcommon.testing.images import get_docker_hub_image
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "0f30e3780e6b"
_PROGRESS_REVISION = "1d10cb8faa04"


def _migration_database() -> Generator[tuple[AlembicConfig, sa.Engine], None, None]:
    with PostgresContainer(
        get_docker_hub_image("postgres:17"),
        driver="psycopg",
    ) as postgres:
        url = postgres.get_connection_url()
        config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        engine = sa.create_engine(url)
        try:
            yield config, engine
        finally:
            engine.dispose()


def _seed_legacy_work(
    connection: sa.Connection,
    *,
    work_id: str,
    binding_id: str,
    status: str,
    tasks: Sequence[Mapping[str, object]],
    desired_progress_payload: dict[str, object] | None,
) -> None:
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_works (
                id,
                binding_id,
                status,
                schema_version,
                tasks,
                state_revision,
                desired_progress_revision,
                desired_progress_payload
            )
            VALUES (
                :id,
                :binding_id,
                :status,
                1,
                CAST(:tasks AS jsonb),
                1,
                1,
                CAST(:desired_progress_payload AS jsonb)
            )
            """
        ),
        {
            "id": work_id,
            "binding_id": binding_id,
            "status": status,
            "tasks": json.dumps(tasks),
            "desired_progress_payload": (
                None
                if desired_progress_payload is None
                else json.dumps(desired_progress_payload)
            ),
        },
    )


def test_provider_native_progress_migration_round_trip(
    check_docker_availability: None,
) -> None:
    del check_docker_availability
    migration_database = _migration_database()
    config, engine = next(migration_database)
    try:
        alembic_command.upgrade(config, _PARENT_REVISION)
        checking_tasks: list[dict[str, object]] = []
        working_tasks = [
            {
                "id": "inspect",
                "title": "Inspect failures",
                "status": "in_progress",
            }
        ]
        finished_tasks = [
            {
                "id": "report",
                "title": "Report findings",
                "status": "completed",
            }
        ]
        with engine.begin() as connection:
            connection.execute(sa.text("SET session_replication_role = replica"))
            _seed_legacy_work(
                connection,
                work_id="work-checking",
                binding_id="binding-checking",
                status="active",
                tasks=checking_tasks,
                desired_progress_payload={
                    "state": "checking",
                    "tasks": checking_tasks,
                },
            )
            _seed_legacy_work(
                connection,
                work_id="work-working",
                binding_id="binding-working",
                status="active",
                tasks=working_tasks,
                desired_progress_payload={
                    "state": "working",
                    "tasks": working_tasks,
                },
            )
            _seed_legacy_work(
                connection,
                work_id="work-finished",
                binding_id="binding-finished",
                status="finished",
                tasks=finished_tasks,
                desired_progress_payload=None,
            )
            connection.execute(sa.text("SET session_replication_role = origin"))

        alembic_command.upgrade(config, _PROGRESS_REVISION)
        with engine.begin() as connection:
            rows = {
                row.id: row
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT
                            id,
                            schema_version,
                            title,
                            tasks,
                            desired_progress_payload
                        FROM external_channel_works
                        ORDER BY id
                        """
                    )
                ).mappings()
            }
            assert rows["work-checking"].title is None
            assert rows["work-checking"].desired_progress_payload == {
                "schema_version": 2,
                "state": "checking",
                "title": None,
                "tasks": [],
            }
            assert rows["work-working"].title == "Inspect failures…"
            assert rows["work-working"].tasks == [
                {
                    "id": "inspect",
                    "title": "Inspect failures",
                    "status": "in_progress",
                    "details": None,
                    "output": None,
                    "sources": [],
                }
            ]
            assert rows["work-working"].desired_progress_payload == {
                "schema_version": 2,
                "state": "working",
                "title": "Inspect failures…",
                "tasks": rows["work-working"].tasks,
            }
            assert rows["work-finished"].title == "Report findings…"
            assert rows["work-finished"].desired_progress_payload is None
            assert all(row.schema_version == 2 for row in rows.values())
            connection.execute(
                sa.text(
                    """
                    UPDATE external_channel_works
                    SET tasks = jsonb_set(tasks, '{0,status}', '"failed"'),
                        desired_progress_payload = jsonb_set(
                            desired_progress_payload,
                            '{tasks,0,status}',
                            '"failed"'
                        )
                    WHERE id = 'work-working'
                    """
                )
            )

        alembic_command.downgrade(config, _PARENT_REVISION)
        with engine.connect() as connection:
            title_column_count = connection.scalar(
                sa.text(
                    """
                    SELECT count(*)
                    FROM information_schema.columns
                    WHERE table_name = 'external_channel_works'
                      AND column_name = 'title'
                    """
                )
            )
            assert title_column_count == 0
            rows = {
                row.id: row
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT
                            id,
                            schema_version,
                            tasks,
                            desired_progress_payload
                        FROM external_channel_works
                        ORDER BY id
                        """
                    )
                ).mappings()
            }
            assert rows["work-checking"].desired_progress_payload == {
                "state": "checking",
                "tasks": [],
            }
            assert rows["work-working"].tasks == [
                {
                    "id": "inspect",
                    "title": "Inspect failures",
                    "status": "pending",
                }
            ]
            assert rows["work-working"].desired_progress_payload == {
                "state": "working",
                "tasks": rows["work-working"].tasks,
            }
            assert rows["work-finished"].desired_progress_payload is None
            assert all(row.schema_version == 1 for row in rows.values())
    finally:
        migration_database.close()
