"""Migration tests for immediate External Channel provider delivery."""

import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT_REVISION = "772e7ab22a8e"
_REVISION = "ef9fddb71222"
_RETIRED_TABLES = {
    "external_channel_actions",
    "external_channel_delivery_attempts",
}
_RETIRED_ENUMS = {
    "external_channel_action_mode",
    "external_channel_delivery_origin_type",
    "external_channel_delivery_operation",
    "external_channel_delivery_status",
}


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    """Return reflected column names for one table."""
    return {column["name"] for column in inspector.get_columns(table_name)}


def _enum_values(connection: sa.Connection, enum_name: str) -> list[str]:
    """Return ordered labels for one PostgreSQL enum."""
    return list(
        connection.scalars(
            sa.text(
                """
                SELECT enumlabel
                FROM pg_enum
                JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
                WHERE pg_type.typname = :enum_name
                ORDER BY enumsortorder
                """
            ),
            {"enum_name": enum_name},
        )
    )


def _enum_names(connection: sa.Connection) -> set[str]:
    """Return installed PostgreSQL enum names."""
    return set(
        connection.scalars(sa.text("SELECT typname FROM pg_type WHERE typtype = 'e'"))
    )


def _seed_legacy_provider_state(connection: sa.Connection) -> None:
    """Seed current owners plus provider-operation history before the cutover."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('cutover-workspace', 'Cutover', 'cutover-migration')
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
                'cutover-agent', 'cutover-workspace', 'Cutover Agent',
                '{}'::jsonb, '{}'::jsonb,
                '[
                    {"label": "cutover-main", "model_selection": {}},
                    {"label": "cutover-light", "model_selection": {}}
                ]'::jsonb,
                'cutover-main', 'cutover-light'
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
                    'cutover-session-one', 'cutover-workspace', 'cutover-agent',
                    'cutover-session-one', 'active', 'external_channel', 'root'
                ),
                (
                    'cutover-session-two', 'cutover-workspace', 'cutover-agent',
                    'cutover-session-two', 'active', 'external_channel', 'root'
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
                'cutover-connection', 'cutover-workspace', 'slack', 'http',
                'slack_http', 'active', 'single', 'cutover-app',
                'cutover-tenant', 'cutover-ciphertext'
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
                'cutover-route', 'cutover-connection', 'cutover-agent',
                'cutover-agent', 'dedicated', 'single', 'available'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_principals (
                id, provider, provider_tenant_id, provider_user_id, author_type
            )
            VALUES (
                'cutover-principal', 'slack', 'cutover-tenant',
                'cutover-user', 'human'
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
                    'cutover-resource-one', 'cutover-connection', 'thread',
                    'cutover-thread-one',
                    '{
                        "provider": "slack",
                        "tenant_id": "cutover-tenant",
                        "channel_id": "cutover-channel",
                        "thread_ts": "1.000001"
                    }'::jsonb,
                    'active'
                ),
                (
                    'cutover-resource-two', 'cutover-connection', 'thread',
                    'cutover-thread-two',
                    '{
                        "provider": "slack",
                        "tenant_id": "cutover-tenant",
                        "channel_id": "cutover-channel",
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
                id, resource_id, route_id, agent_session_id, response_mode
            )
            VALUES
                (
                    'cutover-binding-one', 'cutover-resource-one',
                    'cutover-route', 'cutover-session-one', 'all_messages'
                ),
                (
                    'cutover-binding-two', 'cutover-resource-two',
                    'cutover-route', 'cutover-session-two', 'all_messages'
                )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_works (
                id, binding_id, status, title, tasks,
                desired_progress_revision, desired_progress_payload,
                progress_provider_message_key
            )
            VALUES
                (
                    'cutover-work-one', 'cutover-binding-one', 'active',
                    'Retained Slack projection', '[]'::jsonb, 4,
                    '{"text": "current"}'::jsonb, 'slack-progress-key'
                ),
                (
                    'cutover-work-two', 'cutover-binding-two', 'active',
                    'Pending projection', '[]'::jsonb, 7,
                    '{"text": "pending"}'::jsonb, NULL
                )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_actions (
                id, agent_session_id, client_tool_call_id, binding_id, mode,
                state_revision, request_payload, work_id
            )
            VALUES (
                'cutover-action', 'cutover-session-two', 'tool-call-cutover',
                'cutover-binding-two', 'continue', 7, '{}'::jsonb,
                'cutover-work-two'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_delivery_attempts (
                id, origin_type, origin_id, operation, request_payload, status,
                channel_action_id, binding_id, provider_message_key
            )
            VALUES
                (
                    'cutover-delivery-work', 'channel_action',
                    'cutover-action', 'progress_create', '{}'::jsonb, 'pending',
                    'cutover-action', 'cutover-binding-two',
                    'pending-progress-key'
                ),
                (
                    'cutover-delivery-access', 'access_request',
                    'cutover-access', 'control_message', '{}'::jsonb,
                    'delivered', NULL, 'cutover-binding-one',
                    'access-control-key'
                )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_work_projection_parts (
                id, work_id, part_ordinal, desired_progress_revision, status,
                provider_message_key, latest_delivery_attempt_id
            )
            VALUES (
                'cutover-projection', 'cutover-work-two', 0, 7, 'pending',
                'pending-progress-key', 'cutover-delivery-work'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_access_requests (
                id, route_id, resource_id, trigger_provider_message_key,
                principal_id, status, decision_policy_snapshot, expires_at,
                connection_id, agent_session_id
            )
            VALUES (
                'cutover-access', 'cutover-route', 'cutover-resource-one',
                'trigger-message-key', 'cutover-principal', 'allowed',
                '{}'::jsonb, now() + interval '1 hour',
                'cutover-connection', 'cutover-session-one'
            )
            """
        )
    )


def test_immediate_delivery_cutover_preserves_only_current_projection(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Preserve owner-local identities while discarding provider-operation history."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_legacy_provider_state(connection)

    alembic_runner.migrate_up_to(_REVISION)

    inspector = sa.inspect(alembic_engine)
    assert _RETIRED_TABLES.isdisjoint(inspector.get_table_names())
    assert "progress_provider_message_key" not in _column_names(
        inspector,
        "external_channel_works",
    )
    assert {
        "latest_delivery_attempt_id",
        "deleted_at",
    }.isdisjoint(_column_names(inspector, "external_channel_work_projection_parts"))
    assert {
        "control_provider_message_key",
        "control_projection_status",
    } <= _column_names(inspector, "external_channel_access_requests")

    with alembic_engine.connect() as connection:
        projection_rows = connection.execute(
            sa.text(
                """
                SELECT work_id, part_ordinal, desired_progress_revision,
                       status::text, provider_message_key
                FROM external_channel_work_projection_parts
                ORDER BY work_id
                """
            )
        ).tuples()
        assert projection_rows.all() == [
            (
                "cutover-work-one",
                0,
                4,
                "present",
                "slack-progress-key",
            ),
            (
                "cutover-work-two",
                0,
                7,
                "unknown",
                "pending-progress-key",
            ),
        ]
        access_projection = connection.execute(
            sa.text(
                """
                SELECT control_provider_message_key,
                       control_projection_status::text
                FROM external_channel_access_requests
                WHERE id = 'cutover-access'
                """
            )
        ).one()
        assert access_projection == (None, None)
        assert _RETIRED_ENUMS.isdisjoint(_enum_names(connection))
        assert _enum_values(
            connection,
            "external_channel_work_projection_status",
        ) == ["present", "failed", "unknown", "deleted"]

    alembic_runner.migrate_down_to(_PARENT_REVISION)

    inspector = sa.inspect(alembic_engine)
    assert _RETIRED_TABLES <= set(inspector.get_table_names())
    assert "progress_provider_message_key" in _column_names(
        inspector,
        "external_channel_works",
    )
    assert {
        "latest_delivery_attempt_id",
        "deleted_at",
    } <= _column_names(inspector, "external_channel_work_projection_parts")
    assert {
        "control_provider_message_key",
        "control_projection_status",
    }.isdisjoint(_column_names(inspector, "external_channel_access_requests"))
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text(
                    """
                SELECT progress_provider_message_key
                FROM external_channel_works
                WHERE id = 'cutover-work-one'
                """
                )
            )
            == "slack-progress-key"
        )
        assert (
            connection.scalar(sa.text("SELECT count(*) FROM external_channel_actions"))
            == 0
        )
        assert (
            connection.scalar(
                sa.text("SELECT count(*) FROM external_channel_delivery_attempts")
            )
            == 0
        )
        assert _RETIRED_ENUMS <= _enum_names(connection)
        assert _enum_values(
            connection,
            "external_channel_work_projection_status",
        ) == ["pending", "present", "failed", "unknown", "deleted"]

    alembic_runner.migrate_up_to(_REVISION)
    assert _RETIRED_TABLES.isdisjoint(sa.inspect(alembic_engine).get_table_names())
