"""Migration tests for External Channel Session activation removal."""

import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT_REVISION = "b64a4e25ab8b"
_REVISION = "c67332e97043"
_ACTIVATION_ENUM = "external_channel_session_activation_state"
_ACTIVATION_TABLES = {
    "external_channel_session_activations",
    "external_channel_session_activation_deliveries",
}


def _table_names(engine: Engine) -> set[str]:
    """Return table names in the migration schema."""
    return set(sa.inspect(engine).get_table_names())


def _enum_names(engine: Engine) -> set[str]:
    """Return PostgreSQL enum type names in the migration schema."""
    with engine.connect() as connection:
        return set(
            connection.scalars(
                sa.text(
                    """
                    SELECT typname
                    FROM pg_type
                    WHERE typtype = 'e'
                      AND typnamespace = to_regnamespace('public')
                    """
                )
            )
        )


def _seed_blocked_mailbox(connection: sa.Connection) -> None:
    """Seed one retained mailbox that the removed activation gate blocked."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('activation-workspace', 'Activation', 'activation-removal')
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
                'activation-agent', 'activation-workspace', 'Activation Agent',
                '{}'::jsonb, '{}'::jsonb,
                '[
                    {"label": "activation-main", "model_selection": {}},
                    {"label": "activation-light", "model_selection": {}}
                ]'::jsonb,
                'activation-main', 'activation-light'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status, start_reason,
                session_kind, run_state
            )
            VALUES (
                'activation-session', 'activation-workspace', 'activation-agent',
                'activation-session', 'active', 'external_channel', 'root', 'idle'
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
                'activation-connection', 'activation-workspace', 'slack', 'http',
                'slack_http', 'active', 'single', 'activation-app',
                'activation-tenant'
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
                'activation-route', 'activation-connection', 'activation-agent',
                'activation-agent', 'dedicated', 'single', 'available'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_resources (
                id, connection_id, resource_type, provider_resource_key, status
            )
            VALUES (
                'activation-resource', 'activation-connection', 'thread',
                'slack:activation-tenant:activation-channel:1.000001', 'active'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_conversation_positions (
                id, connection_id, scope_kind, provider_channel_id,
                provider_thread_key, read_through_position
            )
            VALUES (
                'activation-position', 'activation-connection', 'thread',
                'activation-channel', '1.000001', '00000000000000000001'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_bindings (
                id, resource_id, route_id, agent_session_id
            )
            VALUES (
                'activation-binding', 'activation-resource', 'activation-route',
                'activation-session'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO mailbox_items (
                id, session_id, kind, scheduling_mode, idempotency_key, payload
            )
            VALUES (
                'activation-mailbox', 'activation-session',
                'external_channel_invocation', 'wake_session',
                'activation-mailbox-key', '{}'::jsonb
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_session_activations (
                id, connection_id, conversation_position_id, binding_id,
                agent_session_id, trigger_provider_message_key,
                trigger_position, range_start_position, state, mailbox_item_id,
                failure_kind, failure_summary, blocked_at
            )
            VALUES (
                'activation-row', 'activation-connection', 'activation-position',
                'activation-binding', 'activation-session',
                'activation-trigger', '00000000000000000002',
                '00000000000000000001', 'blocked', 'activation-mailbox',
                'execution_cancelled', 'Provider control delivery was cancelled.',
                now()
            )
            """
        )
    )


def test_activation_removal_releases_retained_mailbox_to_cursor_authority(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Advance retained input, wake its Session, and remove activation schema."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_blocked_mailbox(connection)

    assert _ACTIVATION_TABLES <= _table_names(alembic_engine)
    assert _ACTIVATION_ENUM in _enum_names(alembic_engine)

    alembic_runner.migrate_up_to(_REVISION)

    assert _ACTIVATION_TABLES.isdisjoint(_table_names(alembic_engine))
    assert _ACTIVATION_ENUM not in _enum_names(alembic_engine)
    with alembic_engine.connect() as connection:
        position = connection.scalar(
            sa.text(
                "SELECT read_through_position "
                "FROM external_channel_conversation_positions "
                "WHERE id = 'activation-position'"
            )
        )
        run_state = connection.scalar(
            sa.text(
                "SELECT run_state FROM agent_sessions WHERE id = 'activation-session'"
            )
        )
        mailbox_count = connection.scalar(
            sa.text(
                "SELECT COUNT(*) FROM mailbox_items WHERE id = 'activation-mailbox'"
            )
        )

    assert position == "00000000000000000002"
    assert run_state == "running"
    assert mailbox_count == 1

    alembic_runner.migrate_down_to(_PARENT_REVISION)

    assert _ACTIVATION_TABLES <= _table_names(alembic_engine)
    assert _ACTIVATION_ENUM in _enum_names(alembic_engine)
