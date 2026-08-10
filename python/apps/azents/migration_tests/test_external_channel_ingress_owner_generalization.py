"""Migration tests for External Channel conversation ingress owners."""

import pytest
import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT_REVISION = "b53dacd10814"
_REVISION = "346454f625fe"


def _seed_session_queue(connection: sa.Connection) -> None:
    """Seed one compatible Session-keyed ingress item."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('owner-workspace', 'Ingress Owner', 'ingress-owner')
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
                'owner-agent', 'owner-workspace', 'Ingress Owner Agent',
                '{}'::jsonb, '{}'::jsonb,
                '[
                    {"label": "owner-main", "model_selection": {}},
                    {"label": "owner-light", "model_selection": {}}
                ]'::jsonb,
                'owner-main', 'owner-light'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status, start_reason,
                session_kind, run_state, product_mode, primary_kind
            )
            VALUES (
                'owner-session', 'owner-workspace', 'owner-agent',
                'owner-session', 'active', 'external_channel', 'root', 'idle',
                'team', 'team_primary'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_connections (
                id, workspace_id, provider, transport, ingress_profile, status,
                app_mode, provider_app_id, provider_tenant_id
            )
            VALUES (
                'owner-connection', 'owner-workspace', 'slack', 'http',
                'slack_http', 'active', 'single', 'owner-app', 'owner-tenant'
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
                'owner-route', 'owner-connection', 'owner-agent', 'owner-agent',
                'dedicated', 'single', 'available'
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
            VALUES (
                'owner-target', 'owner-connection', 'thread',
                'slack:owner-tenant:owner-channel:1.000001',
                '{
                    "provider": "slack",
                    "tenant_id": "owner-tenant",
                    "channel_id": "owner-channel",
                    "thread_ts": "1.000001"
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
            VALUES (
                'owner-binding', 'owner-target', 'owner-route',
                'owner-session', 'all_messages'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_conversation_positions (
                id, connection_id, scope_kind, provider_channel_id,
                provider_thread_key
            )
            VALUES (
                'owner-position', 'owner-connection', 'thread',
                'owner-channel', '1.000001'
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
                'owner-principal', 'slack', 'owner-tenant', 'owner-user', 'human'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_ingress_sessions (session_id)
            VALUES ('owner-session')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_ingress_items (
                id, session_id, queue_key, deduplication_key, provider_event_id,
                connection_id, provider, ingress_profile,
                configuration_generation, authority_kind, provider_event_type,
                provider_tenant_id, scope_kind, provider_channel_id,
                provider_parent_channel_id, provider_thread_key,
                delivery_thread_key, provider_resource_key, resource_id,
                binding_id, conversation_position_id, principal_id,
                trigger_provider_message_key, trigger_provider_message_id,
                trigger_position, provider_user_id, invocation, invocation_id,
                initial_title_eligible
            )
            VALUES (
                'owner-item', 'owner-session',
                '019fa000000070008000000000000001',
                'owner-deduplication', 'owner-event', 'owner-connection', 'slack',
                'slack_http', 1, 'configuration', 'message',
                'owner-tenant', 'thread', 'owner-channel', 'owner-channel',
                '1.000001', '1.000001',
                'slack:owner-tenant:owner-channel:1.000001', 'owner-target',
                'owner-binding', 'owner-position', 'owner-principal',
                'slack:owner-tenant:owner-channel:1.000001',
                '1.000001', '1.000001', 'owner-user', true,
                'owner-invocation', true
            )
            """
        )
    )


def test_generalization_preserves_ready_queue_round_trip(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Preserve ready owner authority and item identity in both directions."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_session_queue(connection)

    alembic_runner.migrate_up_to(_REVISION)

    with alembic_engine.connect() as connection:
        owner = connection.execute(
            sa.text(
                """
                SELECT connection_id, target_resource_id, route_id, binding_id,
                       session_id, response_mode::text
                FROM external_channel_ingress_owners
                """
            )
        ).one()
        item = connection.execute(
            sa.text(
                """
                SELECT owner_id, source_resource_id, queue_key, attempt_count,
                       state::text
                FROM external_channel_ingress_items
                """
            )
        ).one()
    assert owner == (
        "owner-connection",
        "owner-target",
        "owner-route",
        "owner-binding",
        "owner-session",
        "all_messages",
    )
    assert item[1:] == (
        "owner-target",
        "019fa000000070008000000000000001",
        0,
        "pending",
    )

    alembic_runner.migrate_down_to(_PARENT_REVISION)

    with alembic_engine.connect() as connection:
        restored = connection.execute(
            sa.text(
                """
                SELECT session_id, resource_id, binding_id, queue_key,
                       attempt_count, state::text
                FROM external_channel_ingress_items
                """
            )
        ).one()
    assert restored == (
        "owner-session",
        "owner-target",
        "owner-binding",
        "019fa000000070008000000000000001",
        0,
        "pending",
    )


def test_generalization_backfills_access_request_source_resource(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Preserve the legacy access Resource as the replay source boundary."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_session_queue(connection)
        connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_access_requests (
                    id, route_id, resource_id, trigger_provider_message_key,
                    principal_id, status, decision_policy_snapshot, expires_at,
                    connection_id, conversation_position_id, trigger_position
                )
                VALUES (
                    'owner-access', 'owner-route', 'owner-target',
                    'slack:owner-tenant:owner-channel:1.000001',
                    'owner-principal', 'pending', '{}'::jsonb,
                    now() + interval '1 day', 'owner-connection',
                    'owner-position', '1.000001'
                )
                """
            )
        )

    alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.connect() as connection:
        source_resource_id = connection.scalar(
            sa.text(
                """
                SELECT source_resource_id
                FROM external_channel_access_requests
                WHERE id = 'owner-access'
                """
            )
        )
    assert source_resource_id == "owner-target"

    alembic_runner.migrate_down_to(_PARENT_REVISION)
    with alembic_engine.connect() as connection:
        columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns(
                "external_channel_access_requests"
            )
        }
    assert "source_resource_id" not in columns


def test_downgrade_rejects_source_target_fan_in(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Reject rollback when the old lifecycle cannot preserve source fan-in."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_session_queue(connection)
    alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_resources (
                    id, connection_id, resource_type, provider_resource_key,
                    labels, status
                )
                VALUES (
                    'owner-source', 'owner-connection', 'thread',
                    'slack:owner-tenant:owner-channel:2.000002',
                    '{"thread_ts": "2.000002"}'::jsonb, 'active'
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                UPDATE external_channel_ingress_items
                SET source_resource_id = 'owner-source'
                WHERE id = 'owner-item'
                """
            )
        )

    with pytest.raises(
        RuntimeError,
        match="Session-keyed lifecycle cannot represent",
    ):
        alembic_runner.migrate_down_to(_PARENT_REVISION)


def test_downgrade_rejects_access_source_target_fan_in(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Reject rollback when access replay requires separate source identity."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_session_queue(connection)
        connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_access_requests (
                    id, route_id, resource_id, trigger_provider_message_key,
                    principal_id, status, decision_policy_snapshot, expires_at,
                    connection_id, conversation_position_id, trigger_position
                )
                VALUES (
                    'owner-access', 'owner-route', 'owner-target',
                    'slack:owner-tenant:owner-channel:1.000001',
                    'owner-principal', 'pending', '{}'::jsonb,
                    now() + interval '1 day', 'owner-connection',
                    'owner-position', '1.000001'
                )
                """
            )
        )
    alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_resources (
                    id, connection_id, resource_type, provider_resource_key,
                    labels, status
                )
                VALUES (
                    'owner-source', 'owner-connection', 'thread',
                    'slack:owner-tenant:owner-channel:2.000002',
                    '{"thread_ts": "2.000002"}'::jsonb, 'active'
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                UPDATE external_channel_access_requests
                SET source_resource_id = 'owner-source'
                WHERE id = 'owner-access'
                """
            )
        )

    with pytest.raises(
        RuntimeError,
        match="Session-keyed lifecycle cannot represent",
    ):
        alembic_runner.migrate_down_to(_PARENT_REVISION)


def test_downgrade_rejects_multiple_owners_for_one_session(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Reject rollback when one Session has several conversation owners."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_session_queue(connection)
    alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_resources (
                    id, connection_id, resource_type, provider_resource_key,
                    labels, status
                )
                VALUES (
                    'owner-target-2', 'owner-connection', 'thread',
                    'slack:owner-tenant:owner-channel:2.000002',
                    '{"thread_ts": "2.000002"}'::jsonb, 'active'
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
                VALUES (
                    'owner-binding-2', 'owner-target-2', 'owner-route',
                    'owner-session', 'all_messages'
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_ingress_owners (
                    id, connection_id, target_resource_id, route_id,
                    response_mode, binding_id, session_id
                )
                VALUES (
                    'owner-2', 'owner-connection', 'owner-target-2', 'owner-route',
                    'all_messages', 'owner-binding-2', 'owner-session'
                )
                """
            )
        )

    with pytest.raises(
        RuntimeError,
        match="Session-keyed lifecycle cannot represent",
    ):
        alembic_runner.migrate_down_to(_PARENT_REVISION)
