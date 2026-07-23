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


def _seed_legacy_binding_graph(
    connection: sa.Connection,
    *,
    binding_ids: Sequence[str],
) -> None:
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('workspace-migration', 'Migration test', 'migration-test')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id,
                workspace_id,
                name,
                model_selection,
                lightweight_model_selection,
                selectable_model_options,
                main_model_label,
                lightweight_model_label
            )
            VALUES (
                'agent-migration',
                'workspace-migration',
                'Migration test Agent',
                '{}'::jsonb,
                '{}'::jsonb,
                jsonb_build_array(
                    jsonb_build_object(
                        'label',
                        'migration',
                        'model_selection',
                        '{}'::jsonb
                    )
                ),
                'migration',
                'migration'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id,
                workspace_id,
                agent_id,
                status,
                start_reason,
                handle,
                session_kind
            )
            VALUES (
                'session-migration',
                'workspace-migration',
                'agent-migration',
                'active',
                'external_channel',
                'migration-session',
                'root'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_connections (
                id,
                workspace_id,
                provider,
                transport,
                status
            )
            VALUES (
                'connection-migration',
                'workspace-migration',
                'slack',
                'http',
                'active'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_agent_routes (
                id,
                connection_id,
                agent_id,
                route_mode
            )
            VALUES (
                'route-migration',
                'connection-migration',
                'agent-migration',
                'dedicated'
            )
            """
        )
    )
    for index, binding_id in enumerate(binding_ids):
        resource_id = f"resource-migration-{index}"
        connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_resources (
                    id,
                    connection_id,
                    resource_type,
                    provider_resource_key,
                    status
                )
                VALUES (
                    :id,
                    'connection-migration',
                    'thread',
                    :provider_resource_key,
                    'active'
                )
                """
            ),
            {
                "id": resource_id,
                "provider_resource_key": f"slack:T1:C1:{index}.000001",
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_bindings (
                    id,
                    resource_id,
                    route_id,
                    agent_session_id,
                    status
                )
                VALUES (
                    :binding_id,
                    :resource_id,
                    'route-migration',
                    'session-migration',
                    'active'
                )
                """
            ),
            {
                "binding_id": binding_id,
                "resource_id": resource_id,
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
            _seed_legacy_binding_graph(
                connection,
                binding_ids=(
                    "binding-checking",
                    "binding-working",
                    "binding-finished",
                ),
            )
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
