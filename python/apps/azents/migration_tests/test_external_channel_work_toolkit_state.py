"""Migration tests for External Channel Work Toolkit State ownership."""

import datetime

import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT_REVISION = "ef9fddb71222"
_REVISION = "f6a2c5c503aa"
_RETIRED_TABLES = {
    "external_channel_works",
    "external_channel_work_projection_parts",
}


def _enum_names(connection: sa.Connection) -> set[str]:
    """Return installed PostgreSQL enum names."""
    return set(
        connection.scalars(sa.text("SELECT typname FROM pg_type WHERE typtype = 'e'"))
    )


def _seed_legacy_work(connection: sa.Connection) -> None:
    """Seed active and finished Work history before the Toolkit State cutover."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('work-state-workspace', 'Work State', 'work-state-migration')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id, workspace_id, name, model_selection,
                lightweight_model_selection, selectable_model_options,
                main_model_label, lightweight_model_label
            )
            VALUES (
                'work-state-agent', 'work-state-workspace', 'Work State Agent',
                '{}'::jsonb, '{}'::jsonb,
                '[
                    {"label": "work-main", "model_selection": {}},
                    {"label": "work-light", "model_selection": {}}
                ]'::jsonb,
                'work-main', 'work-light'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status, start_reason,
                session_kind
            )
            VALUES
                (
                    'work-state-session-one', 'work-state-workspace',
                    'work-state-agent', 'work-state-session-one', 'active',
                    'external_channel', 'root'
                ),
                (
                    'work-state-session-two', 'work-state-workspace',
                    'work-state-agent', 'work-state-session-two', 'archived',
                    'external_channel', 'root'
                )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO toolkit_states (
                id, agent_id, session_id, toolkit_namespace, state_name,
                state_json, schema_version, version
            )
            VALUES (
                'work-state-unrelated-state', 'work-state-agent',
                'work-state-session-one', 'external_channel', 'routing',
                '{"schema_version": 1, "value": "preserve"}'::jsonb, 1, 3
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_connections (
                id, workspace_id, provider, transport, ingress_profile, status,
                app_mode, provider_app_id, provider_tenant_id,
                encrypted_credentials
            )
            VALUES (
                'work-state-connection', 'work-state-workspace', 'slack', 'http',
                'slack_http', 'active', 'single', 'work-state-app',
                'work-state-tenant', 'work-state-ciphertext'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_agent_routes (
                id, connection_id, agent_id, agent_id_snapshot, route_mode,
                connection_app_mode, catalog_status
            )
            VALUES (
                'work-state-route', 'work-state-connection', 'work-state-agent',
                'work-state-agent', 'dedicated', 'single', 'available'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_resources (
                id, connection_id, resource_type, provider_resource_key,
                labels, status
            )
            VALUES
                (
                    'work-state-resource-one', 'work-state-connection', 'thread',
                    'work-state-thread-one',
                    '{
                        "provider": "slack",
                        "tenant_id": "work-state-tenant",
                        "channel_id": "work-state-channel",
                        "thread_ts": "1.000001"
                    }'::jsonb,
                    'active'
                ),
                (
                    'work-state-resource-two', 'work-state-connection', 'thread',
                    'work-state-thread-two',
                    '{
                        "provider": "slack",
                        "tenant_id": "work-state-tenant",
                        "channel_id": "work-state-channel",
                        "thread_ts": "2.000002"
                    }'::jsonb,
                    'active'
                )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_bindings (
                id, resource_id, route_id, agent_session_id, response_mode,
                disconnected_at, disconnect_reason
            )
            VALUES
                (
                    'work-state-binding-one', 'work-state-resource-one',
                    'work-state-route', 'work-state-session-one', 'all_messages',
                    NULL, NULL
                ),
                (
                    'work-state-binding-two', 'work-state-resource-two',
                    'work-state-route', 'work-state-session-two', 'mention_only',
                    '2026-08-03 01:00:00+00', 'session_archived'
                )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_works (
                id, binding_id, status, schema_version, title, tasks,
                state_revision, desired_progress_revision,
                desired_progress_payload, finished_at, created_at, updated_at
            )
            VALUES
                (
                    'work-state-old-one', 'work-state-binding-one', 'finished', 2,
                    'Older finished', '[]'::jsonb, 2, 2, NULL,
                    '2026-08-03 00:10:00+00', '2026-08-03 00:00:00+00',
                    '2026-08-03 00:10:00+00'
                ),
                (
                    'work-state-active-one', 'work-state-binding-one', 'active', 2,
                    NULL, '[]'::jsonb, 4, 5,
                    '{
                        "schema_version": 2,
                        "state": "checking",
                        "title": null,
                        "tasks": []
                    }'::jsonb,
                    NULL, '2026-08-03 00:20:00+00',
                    '2026-08-03 00:30:00+00'
                ),
                (
                    'work-state-old-two', 'work-state-binding-two', 'finished', 2,
                    'Older archived', '[]'::jsonb, 3, 3, NULL,
                    '2026-08-03 00:40:00+00', '2026-08-03 00:35:00+00',
                    '2026-08-03 00:40:00+00'
                ),
                (
                    'work-state-latest-two', 'work-state-binding-two', 'finished', 2,
                    'Latest archived',
                    '[{
                        "id": "task-1",
                        "title": "Done",
                        "status": "completed",
                        "details": null,
                        "output": "Complete",
                        "sources": []
                    }]'::jsonb,
                    6, 7, NULL, '2026-08-03 01:00:00+00',
                    '2026-08-03 00:50:00+00', '2026-08-03 01:00:00+00'
                )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_work_projection_parts (
                id, work_id, part_ordinal, desired_progress_revision, status,
                provider_message_key
            )
            VALUES
                (
                    'work-state-old-part', 'work-state-old-one', 0, 2,
                    'deleted', NULL
                ),
                (
                    'work-state-active-part-zero', 'work-state-active-one', 0, 5,
                    'present', 'provider-active-zero'
                ),
                (
                    'work-state-active-part-one', 'work-state-active-one', 1, 5,
                    'unknown', NULL
                ),
                (
                    'work-state-latest-part', 'work-state-latest-two', 0, 7,
                    'failed', 'provider-latest'
                )
            """
        )
    )


def test_work_cutover_preserves_active_or_latest_state(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Backfill one independent current/latest Toolkit State row per binding."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_legacy_work(connection)

    alembic_runner.migrate_up_to(_REVISION)

    inspector = sa.inspect(alembic_engine)
    assert _RETIRED_TABLES.isdisjoint(inspector.get_table_names())
    with alembic_engine.connect() as connection:
        assert "external_channel_work_status" not in _enum_names(connection)
        rows = connection.execute(
            sa.text(
                """
                SELECT agent_id, session_id, toolkit_namespace, state_name,
                       schema_version, version, state_json
                FROM toolkit_states
                WHERE toolkit_namespace = 'external_channel'
                  AND state_name LIKE 'channel_work:%'
                ORDER BY state_name
                """
            )
        ).mappings()
        states = list(rows)

    assert len(states) == 2
    first = states[0]
    assert first["agent_id"] == "work-state-agent"
    assert first["session_id"] == "work-state-session-one"
    assert first["toolkit_namespace"] == "external_channel"
    assert first["state_name"] == "channel_work:work-state-binding-one"
    assert first["schema_version"] == 1
    assert first["version"] == 1
    assert first["state_json"] == {
        "schema_version": 1,
        "binding_id": "work-state-binding-one",
        "work_cycle_id": "work-state-active-one",
        "status": "active",
        "title": None,
        "tasks": [],
        "state_revision": 4,
        "desired_progress_revision": 5,
        "desired_progress": {
            "schema_version": 2,
            "state": "checking",
            "title": None,
            "tasks": [],
        },
        "finished_at": None,
        "projection_parts": [
            {
                "part_ordinal": 0,
                "desired_progress_revision": 5,
                "status": "present",
                "provider_message_key": "provider-active-zero",
            },
            {
                "part_ordinal": 1,
                "desired_progress_revision": 5,
                "status": "unknown",
                "provider_message_key": None,
            },
        ],
    }
    second = states[1]
    assert second["session_id"] == "work-state-session-two"
    assert second["state_name"] == "channel_work:work-state-binding-two"
    assert second["state_json"]["work_cycle_id"] == "work-state-latest-two"
    assert second["state_json"]["title"] == "Latest archived"
    assert second["state_json"]["tasks"][0]["id"] == "task-1"
    assert datetime.datetime.fromisoformat(
        second["state_json"]["finished_at"]
    ) == datetime.datetime(2026, 8, 3, 1, 0, tzinfo=datetime.UTC)
    assert second["state_json"]["projection_parts"] == [
        {
            "part_ordinal": 0,
            "desired_progress_revision": 7,
            "status": "failed",
            "provider_message_key": "provider-latest",
        }
    ]

    alembic_runner.migrate_down_to(_PARENT_REVISION)

    inspector = sa.inspect(alembic_engine)
    assert _RETIRED_TABLES <= set(inspector.get_table_names())
    with alembic_engine.connect() as connection:
        assert "external_channel_work_status" in _enum_names(connection)
        reconstructed = connection.execute(
            sa.text(
                """
                SELECT id, binding_id, status::text, title,
                       state_revision, desired_progress_revision,
                       desired_progress_payload, finished_at
                FROM external_channel_works
                ORDER BY binding_id
                """
            )
        ).tuples()
        assert reconstructed.all() == [
            (
                "work-state-active-one",
                "work-state-binding-one",
                "active",
                None,
                4,
                5,
                {
                    "schema_version": 2,
                    "state": "checking",
                    "title": None,
                    "tasks": [],
                },
                None,
            ),
            (
                "work-state-latest-two",
                "work-state-binding-two",
                "finished",
                "Latest archived",
                6,
                7,
                None,
                datetime.datetime(2026, 8, 3, 1, 0, tzinfo=datetime.UTC),
            ),
        ]
        projection_parts = connection.execute(
            sa.text(
                """
                SELECT work_id, part_ordinal, desired_progress_revision,
                       status::text, provider_message_key
                FROM external_channel_work_projection_parts
                ORDER BY work_id, part_ordinal
                """
            )
        ).tuples()
        assert projection_parts.all() == [
            (
                "work-state-active-one",
                0,
                5,
                "present",
                "provider-active-zero",
            ),
            ("work-state-active-one", 1, 5, "unknown", None),
            (
                "work-state-latest-two",
                0,
                7,
                "failed",
                "provider-latest",
            ),
        ]
        assert (
            connection.scalar(
                sa.text(
                    """
                    SELECT count(*)
                    FROM toolkit_states
                    WHERE toolkit_namespace = 'external_channel'
                      AND state_name LIKE 'channel_work:%'
                    """
                )
            )
            == 0
        )
        assert (
            connection.scalar(
                sa.text(
                    """
                SELECT state_json ->> 'value'
                FROM toolkit_states
                WHERE id = 'work-state-unrelated-state'
                """
                )
            )
            == "preserve"
        )

    alembic_runner.migrate_up_to(_REVISION)
    assert _RETIRED_TABLES.isdisjoint(sa.inspect(alembic_engine).get_table_names())
