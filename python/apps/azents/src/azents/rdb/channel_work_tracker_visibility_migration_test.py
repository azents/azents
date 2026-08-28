"""PostgreSQL migration tests for Channel Work Tracker visibility."""

import json
from collections.abc import Generator, Mapping
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "ff79e1119f1d"
_VISIBILITY_REVISION = "2c2b5240fe20"


@contextmanager
def _migration_database() -> Generator[tuple[AlembicConfig, sa.Engine]]:
    """Create an isolated PostgreSQL database for migration verification."""
    with PostgresContainer("postgres:17", driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        engine = sa.create_engine(url)
        try:
            yield config, engine
        finally:
            engine.dispose()


def _seed_session(connection: sa.Connection) -> None:
    """Seed the minimum Agent Session graph required by Toolkit State."""
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('workspace-tracker-visibility', 'Tracker visibility', 'tracker-vis')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id, workspace_id, name, model_selection, lightweight_model_selection,
                selectable_model_options, main_model_label, lightweight_model_label
            )
            VALUES (
                'agent-tracker-visibility',
                'workspace-tracker-visibility',
                'Tracker visibility Agent',
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
        sa.text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status, start_reason, session_kind,
                product_mode
            )
            VALUES (
                'session-tracker-visibility',
                'workspace-tracker-visibility',
                'agent-tracker-visibility',
                'tracker-visibility-session',
                'active',
                'initial',
                'root',
                'team'
            )
            """
        )
    )


def _work_payload(
    binding_id: str,
    *,
    status: str = "active",
    desired_progress: dict[str, object] | None = None,
    projection_parts: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build one pre-visibility Channel Work Toolkit State payload."""
    return {
        "schema_version": 1,
        "binding_id": binding_id,
        "work_cycle_id": f"cycle-{binding_id}",
        "status": status,
        "title": f"Work {binding_id}",
        "tasks": [],
        "state_revision": 3,
        "desired_progress_revision": 2,
        "desired_progress": desired_progress,
        "finished_at": "2026-08-28T00:00:00+00:00" if status == "finished" else None,
        "projection_parts": projection_parts or [],
    }


def _task_payload(task_id: str) -> dict[str, object]:
    """Build one valid persisted Channel Work task payload."""
    return {
        "id": task_id,
        "title": f"Task {task_id}",
        "status": "in_progress",
        "details": None,
        "output": None,
        "sources": [],
    }


def _working_progress_payload() -> dict[str, object]:
    """Build one valid non-null desired progress payload."""
    return {
        "schema_version": 2,
        "state": "working",
        "title": "Projected",
        "tasks": [_task_payload("progress-task")],
    }


def _insert_state(
    connection: sa.Connection,
    *,
    state_id: str,
    namespace: str,
    state_name: str,
    state_json: Mapping[str, object],
    schema_version: int,
    version: int = 7,
) -> None:
    """Insert one representative Toolkit State row."""
    connection.execute(
        sa.text(
            """
            INSERT INTO toolkit_states (
                id, agent_id, session_id, toolkit_namespace, state_name,
                state_json, schema_version, version
            )
            VALUES (
                :id,
                'agent-tracker-visibility',
                'session-tracker-visibility',
                :namespace,
                :state_name,
                CAST(:state_json AS jsonb),
                :schema_version,
                :version
            )
            """
        ),
        {
            "id": state_id,
            "namespace": namespace,
            "state_name": state_name,
            "state_json": json.dumps(state_json),
            "schema_version": schema_version,
            "version": version,
        },
    )


def _states(connection: sa.Connection) -> dict[str, dict[str, object]]:
    """Return Toolkit State rows keyed by their stable name."""
    rows = connection.execute(
        sa.text(
            """
            SELECT state_name, state_json, schema_version, version
            FROM toolkit_states
            ORDER BY state_name
            """
        )
    ).mappings()
    return {
        str(row["state_name"]): {
            "state_json": row["state_json"],
            "schema_version": row["schema_version"],
            "version": row["version"],
        }
        for row in rows
    }


def test_tracker_visibility_migration_grandfathers_only_channel_work_state(
    check_docker_availability: None,
) -> None:
    """Upgrade and downgrade preserve Work payloads and unrelated Toolkit State."""
    del check_docker_availability
    work_payloads = {
        "channel_work:binding-active": _work_payload("binding-active"),
        "channel_work:binding-finished": _work_payload(
            "binding-finished",
            status="finished",
        ),
        "channel_work:binding-projected": _work_payload(
            "binding-projected",
            desired_progress=_working_progress_payload(),
            projection_parts=[
                {
                    "part_ordinal": 0,
                    "desired_progress_revision": 2,
                    "status": "present",
                    "provider_message_key": "message-projected",
                }
            ],
        ),
        "channel_work:binding-slack": _work_payload("binding-slack"),
    }
    unrelated_external = {"schema_version": 1, "state": "scheduled"}
    unrelated_namespace = {"schema_version": 1, "state": "unrelated"}

    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            for ordinal, (state_name, payload) in enumerate(work_payloads.items()):
                _insert_state(
                    connection,
                    state_id=f"work-tracker-{ordinal}",
                    namespace="external_channel",
                    state_name=state_name,
                    state_json=payload,
                    schema_version=1,
                )
            _insert_state(
                connection,
                state_id="unrelated-external",
                namespace="external_channel",
                state_name="scheduled_task:binding-active",
                state_json=unrelated_external,
                schema_version=1,
            )
            _insert_state(
                connection,
                state_id="unrelated-namespace",
                namespace="other",
                state_name="channel_work:other-binding",
                state_json=unrelated_namespace,
                schema_version=1,
            )

        alembic_command.upgrade(config, _VISIBILITY_REVISION)
        with engine.connect() as connection:
            upgraded = _states(connection)

        for state_name, expected_payload in work_payloads.items():
            assert upgraded[state_name]["schema_version"] == 2
            assert upgraded[state_name]["version"] == 8
            assert upgraded[state_name]["state_json"] == {
                **expected_payload,
                "schema_version": 2,
                "tracker_visibility": "visible",
            }
        assert upgraded["scheduled_task:binding-active"] == {
            "schema_version": 1,
            "version": 7,
            "state_json": unrelated_external,
        }
        assert upgraded["channel_work:other-binding"] == {
            "schema_version": 1,
            "version": 7,
            "state_json": unrelated_namespace,
        }
        with engine.connect() as connection:
            unrelated_namespace_row = (
                connection.execute(
                    sa.text(
                        """
                    SELECT state_json, schema_version, version
                    FROM toolkit_states
                    WHERE toolkit_namespace = 'other'
                      AND state_name = 'channel_work:other-binding'
                    """
                    )
                )
                .mappings()
                .one()
            )
        assert dict(unrelated_namespace_row) == {
            "state_json": unrelated_namespace,
            "schema_version": 1,
            "version": 7,
        }

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE toolkit_states
                    SET state_json = jsonb_set(
                        state_json,
                        '{tracker_visibility}',
                        '"hidden"'::jsonb,
                        false
                    )
                    WHERE toolkit_namespace = 'external_channel'
                      AND state_name = 'channel_work:binding-active'
                    """
                )
            )
        alembic_command.downgrade(config, _PARENT_REVISION)
        with engine.connect() as connection:
            downgraded = _states(connection)

        for state_name, expected_payload in work_payloads.items():
            assert downgraded[state_name] == {
                "schema_version": 1,
                "version": 9,
                "state_json": expected_payload,
            }
        assert downgraded["scheduled_task:binding-active"] == {
            "schema_version": 1,
            "version": 7,
            "state_json": unrelated_external,
        }


def test_tracker_visibility_migration_rejects_malformed_channel_work_state(
    check_docker_availability: None,
) -> None:
    """Upgrade fails closed without rewriting malformed targeted Toolkit State."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            malformed = _work_payload("binding-malformed")
            del malformed["work_cycle_id"]
            _insert_state(
                connection,
                state_id="work-tracker-malformed",
                namespace="external_channel",
                state_name="channel_work:binding-malformed",
                state_json=malformed,
                schema_version=1,
            )

        with pytest.raises(
            RuntimeError,
            match="Channel Work Toolkit State schema payload is malformed",
        ):
            alembic_command.upgrade(config, _VISIBILITY_REVISION)

        with engine.connect() as connection:
            malformed_state = (
                connection.execute(
                    sa.text(
                        """
                    SELECT state_json, schema_version, version
                    FROM toolkit_states
                    WHERE id = 'work-tracker-malformed'
                    """
                    )
                )
                .mappings()
                .one()
            )
        assert dict(malformed_state) == {
            "state_json": malformed,
            "schema_version": 1,
            "version": 7,
        }


@pytest.mark.parametrize(
    "malformed_field",
    ["tasks", "desired_progress"],
)
def test_tracker_visibility_migration_rejects_malformed_nested_upgrade_state(
    check_docker_availability: None,
    malformed_field: str,
) -> None:
    """Upgrade fails closed for malformed nested v1 Work payloads."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            malformed = _work_payload(
                f"binding-malformed-{malformed_field}",
                desired_progress=_working_progress_payload(),
            )
            if malformed_field == "tasks":
                malformed["tasks"] = [
                    {
                        **_task_payload("top-level-task"),
                        "sources": [{"url": "https://example.com"}],
                    }
                ]
            else:
                malformed["desired_progress"] = {
                    "schema_version": 2,
                    "title": "Missing state",
                    "tasks": [_task_payload("progress-task")],
                }
            _insert_state(
                connection,
                state_id=f"work-malformed-{malformed_field}",
                namespace="external_channel",
                state_name=f"channel_work:binding-malformed-{malformed_field}",
                state_json=malformed,
                schema_version=1,
            )

        with pytest.raises(
            RuntimeError,
            match="Channel Work Toolkit State schema payload is malformed",
        ):
            alembic_command.upgrade(config, _VISIBILITY_REVISION)

        with engine.connect() as connection:
            malformed_state = (
                connection.execute(
                    sa.text(
                        """
                        SELECT state_json, schema_version, version
                        FROM toolkit_states
                        WHERE id = :state_id
                        """
                    ),
                    {"state_id": f"work-malformed-{malformed_field}"},
                )
                .mappings()
                .one()
            )
        assert dict(malformed_state) == {
            "state_json": malformed,
            "schema_version": 1,
            "version": 7,
        }


def test_tracker_visibility_migration_rejects_malformed_nested_downgrade_state(
    check_docker_availability: None,
) -> None:
    """Downgrade fails closed for malformed nested v2 projection state."""
    del check_docker_availability
    payload = _work_payload(
        "binding-malformed-downgrade",
        desired_progress=_working_progress_payload(),
    )
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            _insert_state(
                connection,
                state_id="work-malformed-downgrade",
                namespace="external_channel",
                state_name="channel_work:binding-malformed-downgrade",
                state_json=payload,
                schema_version=1,
            )
        alembic_command.upgrade(config, _VISIBILITY_REVISION)
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE toolkit_states
                    SET state_json = jsonb_set(
                        state_json,
                        '{projection_parts}',
                        '[{
                            "part_ordinal": 0,
                            "desired_progress_revision": 1,
                            "status": "present"
                        }]'::jsonb,
                        false
                    )
                    WHERE id = 'work-malformed-downgrade'
                    """
                )
            )

        with pytest.raises(
            RuntimeError,
            match="Channel Work Toolkit State schema payload is malformed",
        ):
            alembic_command.downgrade(config, _PARENT_REVISION)

        with engine.connect() as connection:
            malformed_state = (
                connection.execute(
                    sa.text(
                        """
                        SELECT state_json, schema_version, version
                        FROM toolkit_states
                        WHERE id = 'work-malformed-downgrade'
                        """
                    )
                )
                .mappings()
                .one()
            )
        assert dict(malformed_state) == {
            "state_json": {
                **payload,
                "schema_version": 2,
                "tracker_visibility": "visible",
                "projection_parts": [
                    {
                        "part_ordinal": 0,
                        "desired_progress_revision": 1,
                        "status": "present",
                    }
                ],
            },
            "schema_version": 2,
            "version": 8,
        }


@pytest.mark.parametrize(
    "malformed_case",
    [
        "ftp_source_url",
        "credential_source_url",
        "duplicate_desired_task_ids",
        "negative_revision",
        "fractional_ordinal",
        "invalid_finished_timestamp",
        "active_finished_timestamp",
        "overlength_task_title",
        "oversized_desired_progress",
    ],
)
def test_tracker_visibility_migration_rejects_semantic_upgrade_payloads(
    check_docker_availability: None,
    malformed_case: str,
) -> None:
    """Upgrade rejects v1 payloads that the frozen post-migration decoder rejects."""
    del check_docker_availability
    binding_id = f"binding-semantic-{malformed_case}"
    payload = _work_payload(
        binding_id,
        desired_progress=_working_progress_payload(),
    )
    if malformed_case == "ftp_source_url":
        payload["tasks"] = [
            {
                **_task_payload("source-task"),
                "sources": [{"url": "ftp://example.com/file", "label": "FTP"}],
            }
        ]
    elif malformed_case == "credential_source_url":
        payload["tasks"] = [
            {
                **_task_payload("source-task"),
                "sources": [
                    {
                        "url": "https://user:password@example.com/file",
                        "label": "Credential",
                    }
                ],
            }
        ]
    elif malformed_case == "duplicate_desired_task_ids":
        payload["desired_progress"] = {
            **_working_progress_payload(),
            "tasks": [_task_payload("duplicate"), _task_payload("duplicate")],
        }
    elif malformed_case == "negative_revision":
        payload["state_revision"] = -1
    elif malformed_case == "fractional_ordinal":
        payload["projection_parts"] = [
            {
                "part_ordinal": 0.5,
                "desired_progress_revision": 1,
                "status": "present",
                "provider_message_key": "projection-fraction",
            }
        ]
    elif malformed_case == "invalid_finished_timestamp":
        payload["status"] = "finished"
        payload["finished_at"] = "not-a-timestamp"
    elif malformed_case == "active_finished_timestamp":
        payload["finished_at"] = "2026-08-28T00:00:00+00:00"
    elif malformed_case == "overlength_task_title":
        payload["tasks"] = [
            {
                **_task_payload("long-title"),
                "title": "x" * 501,
            }
        ]
    elif malformed_case == "oversized_desired_progress":
        payload["desired_progress"] = {
            "schema_version": 2,
            "state": "working",
            "title": "Oversized",
            "tasks": [
                {
                    **_task_payload(f"task-{ordinal}"),
                    "output": "x" * 3_000,
                }
                for ordinal in range(49)
            ],
        }
    else:
        raise AssertionError(f"Unexpected malformed case: {malformed_case}")
    state_id = f"semantic-{malformed_case}"[:32]

    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            _insert_state(
                connection,
                state_id=state_id,
                namespace="external_channel",
                state_name=f"channel_work:{binding_id}",
                state_json=payload,
                schema_version=1,
            )

        with pytest.raises(
            RuntimeError,
            match="Channel Work Toolkit State schema payload is malformed",
        ):
            alembic_command.upgrade(config, _VISIBILITY_REVISION)

        with engine.connect() as connection:
            state = (
                connection.execute(
                    sa.text(
                        """
                        SELECT state_json, schema_version, version
                        FROM toolkit_states
                        WHERE id = :state_id
                        """
                    ),
                    {"state_id": state_id},
                )
                .mappings()
                .one()
            )
        assert dict(state) == {
            "state_json": payload,
            "schema_version": 1,
            "version": 7,
        }


@pytest.mark.parametrize(
    "projection_parts",
    [
        [
            {
                "part_ordinal": 1,
                "desired_progress_revision": 1,
                "status": "present",
                "provider_message_key": "projection-first",
            },
            {
                "part_ordinal": 0,
                "desired_progress_revision": 1,
                "status": "present",
                "provider_message_key": "projection-second",
            },
        ],
        [
            {
                "part_ordinal": 0,
                "desired_progress_revision": 1,
                "status": "present",
                "provider_message_key": "projection-first",
            },
            {
                "part_ordinal": 0,
                "desired_progress_revision": 2,
                "status": "failed",
                "provider_message_key": None,
            },
        ],
    ],
    ids=["unsorted", "duplicate_ordinal"],
)
def test_tracker_visibility_migration_rejects_semantic_downgrade_payloads(
    check_docker_availability: None,
    projection_parts: list[dict[str, object]],
) -> None:
    """Downgrade rejects v2 projection order that cannot decode as Channel Work."""
    del check_docker_availability
    payload = _work_payload(
        "binding-semantic-downgrade",
        desired_progress=_working_progress_payload(),
    )
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            _insert_state(
                connection,
                state_id="work-semantic-downgrade",
                namespace="external_channel",
                state_name="channel_work:binding-semantic-downgrade",
                state_json=payload,
                schema_version=1,
            )
        alembic_command.upgrade(config, _VISIBILITY_REVISION)
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE toolkit_states
                    SET state_json = jsonb_set(
                        state_json,
                        '{projection_parts}',
                        CAST(:projection_parts AS jsonb),
                        false
                    )
                    WHERE id = 'work-semantic-downgrade'
                    """
                ),
                {"projection_parts": json.dumps(projection_parts)},
            )

        with pytest.raises(
            RuntimeError,
            match="Channel Work Toolkit State schema payload is malformed",
        ):
            alembic_command.downgrade(config, _PARENT_REVISION)

        with engine.connect() as connection:
            state = (
                connection.execute(
                    sa.text(
                        """
                        SELECT state_json, schema_version, version
                        FROM toolkit_states
                        WHERE id = 'work-semantic-downgrade'
                        """
                    )
                )
                .mappings()
                .one()
            )
        assert dict(state) == {
            "state_json": {
                **payload,
                "schema_version": 2,
                "tracker_visibility": "visible",
                "projection_parts": projection_parts,
            },
            "schema_version": 2,
            "version": 8,
        }
