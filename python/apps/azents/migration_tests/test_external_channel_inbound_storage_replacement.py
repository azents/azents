"""Migration tests for External Channel inbound storage replacement."""

import hashlib

import pytest
import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_REPAIR_PARENT_REVISION = "d307822ec9d7"
_REPAIR_REVISION = "699b38c35430"
_PARENT_REVISION = _REPAIR_REVISION
_REVISION = "7f4c2a9d1b6e"
_RETIRED_TABLES = {
    "external_channel_messages",
    "external_channel_message_revisions",
    "external_channel_invocation_batches",
    "external_channel_invocation_batch_items",
    "external_channel_conversation_admissions",
    "external_channel_resource_provisionings",
}
_RETIRED_ENUMS = {
    "external_channel_conversation_admission_origin",
    "external_channel_conversation_admission_status",
    "external_channel_invocation_wake_dispatch_status",
    "external_channel_message_lifecycle",
    "external_channel_message_revision_kind",
    "external_channel_resource_provisioning_operation",
    "external_channel_resource_provisioning_status",
}


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    """Return the reflected column names for one table."""
    return {column["name"] for column in inspector.get_columns(table)}


def _enum_names(connection: sa.Connection) -> set[str]:
    """Return installed PostgreSQL enum names."""
    return set(
        connection.scalars(
            sa.text(
                """
                SELECT typname
                FROM pg_type
                WHERE typtype = 'e'
                """
            )
        )
    )


def _selector_provider_key(connection_id: str, provider_message_key: str) -> str:
    digest = hashlib.sha256(
        f"{connection_id}\0{provider_message_key}".encode()
    ).hexdigest()
    return f"agent-selector:{digest}"


def _seed_parent_graph(connection: sa.Connection) -> None:
    """Seed retained replay owners plus terminal legacy processing rows."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('replace-workspace', 'Replacement', 'replace-migration')
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
                'replace-agent', 'replace-workspace', 'Replacement Agent',
                '{}'::jsonb, '{}'::jsonb,
                '[
                    {"label": "replace-main", "model_selection": {}},
                    {"label": "replace-light", "model_selection": {}}
                ]'::jsonb,
                'replace-main', 'replace-light'
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
            VALUES (
                'replace-session', 'replace-workspace', 'replace-agent',
                'replace-session', 'active', 'external_channel', 'root'
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
                'replace-connection', 'replace-workspace', 'slack', 'http',
                'slack_http', 'active', 'multi', 'replace-app', 'replace-tenant'
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
                'replace-route', 'replace-connection', 'replace-agent',
                'replace-agent', 'dedicated', 'multi', 'available'
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
                'replace-principal', 'slack', 'replace-tenant',
                'replace-provider-user', 'human'
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
                'replace-resource', 'replace-connection', 'thread',
                'slack:replace-tenant:replace-channel:1.000001',
                '{"thread_ts": "1.000001"}'::jsonb, 'active'
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
                'replace-position', 'replace-connection', 'parent_channel',
                'replace-channel', NULL, '00000000000000000000.000000'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_messages (
                id, resource_id, provider_message_key, provider_position,
                lifecycle, author_type, principal_id
            )
            VALUES (
                'replace-message', 'replace-resource',
                'slack:replace-tenant:replace-channel:1.000001',
                '00000000000000000001.000001', 'current', 'human',
                'replace-principal'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_message_revisions (
                id, message_id, revision_key, revision_kind, normalized_body,
                attachment_metadata, reference_mappings
            )
            VALUES (
                'replace-revision', 'replace-message', 'v1', 'original',
                'Replacement message', '{}'::jsonb, '{}'::jsonb
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE external_channel_messages
            SET current_revision_id = 'replace-revision'
            WHERE id = 'replace-message'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_bindings (
                id, resource_id, route_id, agent_session_id, status
            )
            VALUES (
                'replace-binding', 'replace-resource', 'replace-route',
                'replace-session', 'active'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_invocation_batches (
                id, binding_id, trigger_message_id, first_provider_position,
                last_provider_position, connection_id,
                conversation_position_id, range_start_position,
                trigger_position, wake_dispatch_status
            )
            VALUES (
                'replace-batch', 'replace-binding', 'replace-message',
                '00000000000000000001.000001',
                '00000000000000000001.000001', 'replace-connection',
                'replace-position', '00000000000000000000.000000',
                '00000000000000000001.000001', 'dispatched'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_invocation_batch_items (
                id, batch_id, message_revision_id, sequence, provider_position
            )
            VALUES (
                'replace-batch-item', 'replace-batch', 'replace-revision', 0,
                '00000000000000000001.000001'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_access_requests (
                id, route_id, resource_id, source_message_id, principal_id,
                status, decision_policy_snapshot, expires_at, connection_id,
                conversation_position_id, range_start_position, trigger_position
            )
            VALUES (
                'replace-access', 'replace-route', 'replace-resource',
                'replace-message', 'replace-principal', 'pending', '{}'::jsonb,
                now() + interval '1 hour', 'replace-connection',
                'replace-position', '00000000000000000000.000000',
                '00000000000000000001.000001'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_conversation_admissions (
                id, connection_id, resource_id, source_message_id, origin,
                status, expires_at, initiating_principal_id,
                conversation_position_id, range_start_position, trigger_position
            )
            VALUES (
                'replace-admission', 'replace-connection', 'replace-resource',
                'replace-message', 'mention_selector', 'pending_selection',
                now() + interval '1 hour', 'replace-principal',
                'replace-position', '00000000000000000000.000000',
                '00000000000000000001.000001'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_resource_provisionings (
                id, resource_id, conversation_admission_id, operation,
                target_provider_resource_key, status,
                confirmed_provider_resource_key
            )
            VALUES (
                'replace-provisioning', 'replace-resource',
                'replace-admission', 'thread_create',
                'slack:replace-tenant:replace-channel:1.000001', 'delivered',
                'slack:replace-tenant:replace-channel:1.000001'
            )
            """
        )
    )


def _seed_promoted_event(connection: sa.Connection) -> None:
    """Record complete durable promotion evidence for the seeded batch."""
    connection.execute(
        sa.text(
            """
            UPDATE external_channel_conversation_positions
            SET read_through_position = '00000000000000000001.000001'
            WHERE id = 'replace-position'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO events (
                id, session_id, kind, payload, external_id, model_order
            )
            VALUES (
                'replace-event',
                'replace-session',
                'external_channel_message',
                jsonb_build_object(
                    'binding_id', 'replace-binding',
                    'invocation_batch_id', 'replace-batch',
                    'external_message_id', 'replace-message',
                    'revision_id', 'replace-revision',
                    'projection_root_id',
                        'external-channel:replace-binding:replace-message'
                ),
                'external-channel:replace-binding:replace-message',
                1
            )
            """
        )
    )


def test_repair_terminalizes_fully_promoted_undispatched_wake(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Allow cutover after exact durable events prove mailbox promotion."""
    alembic_runner.migrate_up_to(_REPAIR_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_parent_graph(connection)
        connection.execute(
            sa.text(
                """
                UPDATE external_channel_invocation_batches
                SET wake_dispatch_status = 'pending'
                WHERE id = 'replace-batch'
                """
            )
        )
        _seed_promoted_event(connection)

    alembic_runner.migrate_up_to(_REPAIR_REVISION)

    with alembic_engine.connect() as connection:
        wake = (
            connection.execute(
                sa.text(
                    """
                    SELECT wake_dispatch_status::text, wake_dispatch_claimed_at
                    FROM external_channel_invocation_batches
                    WHERE id = 'replace-batch'
                    """
                )
            )
            .tuples()
            .one()
        )
        assert wake == ("dispatched", None)

    alembic_runner.migrate_up_to(_REVISION)
    assert _RETIRED_TABLES.isdisjoint(sa.inspect(alembic_engine).get_table_names())


def test_repair_leaves_unproven_undispatched_wake_blocking_cutover(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Keep fail-closed behavior when one retained revision lacks an event."""
    alembic_runner.migrate_up_to(_REPAIR_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_parent_graph(connection)
        connection.execute(
            sa.text(
                """
                UPDATE external_channel_invocation_batches
                SET wake_dispatch_status = 'pending'
                WHERE id = 'replace-batch'
                """
            )
        )
        connection.execute(
            sa.text(
                """
                UPDATE external_channel_conversation_positions
                SET read_through_position = '00000000000000000001.000001'
                WHERE id = 'replace-position'
                """
            )
        )

    alembic_runner.migrate_up_to(_REPAIR_REVISION)

    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text(
                    """
                    SELECT wake_dispatch_status::text
                    FROM external_channel_invocation_batches
                    WHERE id = 'replace-batch'
                    """
                )
            )
            == "pending"
        )
    with pytest.raises(RuntimeError, match="invocation_wake_undispatched=1"):
        alembic_runner.migrate_up_to(_REVISION)


def test_replacement_backfills_replay_identity_and_open_selector(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Preserve content-free replay owners before dropping legacy storage."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_parent_graph(connection)

    alembic_runner.migrate_up_to(_REVISION)

    inspector = sa.inspect(alembic_engine)
    assert _RETIRED_TABLES.isdisjoint(inspector.get_table_names())
    assert "source_message_id" not in _column_names(
        inspector,
        "external_channel_access_requests",
    )
    assert "trigger_provider_message_key" in _column_names(
        inspector,
        "external_channel_access_requests",
    )
    with alembic_engine.connect() as connection:
        assert (
            connection.execute(
                sa.text(
                    """
                SELECT trigger_provider_message_key
                FROM external_channel_access_requests
                WHERE id = 'replace-access'
                """
                )
            ).scalar_one()
            == "slack:replace-tenant:replace-channel:1.000001"
        )
        selector = (
            connection.execute(
                sa.text(
                    """
                SELECT provider_interaction_key, interaction_type, action_id,
                       principal_id, status::text, projection
                FROM external_channel_interactions
                WHERE id = 'replace-admission'
                """
                )
            )
            .mappings()
            .one()
        )
        assert selector["provider_interaction_key"] == _selector_provider_key(
            "replace-connection",
            "slack:replace-tenant:replace-channel:1.000001",
        )
        assert selector["interaction_type"] == "management_action"
        assert selector["action_id"] == "agent_selector"
        assert selector["principal_id"] == "replace-principal"
        assert selector["status"] == "accepted"
        assert selector["projection"] == {
            "agent_selector": {
                "connection_id": "replace-connection",
                "resource_id": "replace-resource",
                "principal_id": "replace-principal",
                "conversation_position_id": "replace-position",
                "trigger_provider_message_key": (
                    "slack:replace-tenant:replace-channel:1.000001"
                ),
                "range_start_position": "00000000000000000000.000000",
                "trigger_position": "00000000000000000001.000001",
                "selected_route_id": None,
            }
        }
        assert _RETIRED_ENUMS.isdisjoint(_enum_names(connection))


@pytest.mark.parametrize(
    ("update_sql", "expected_error"),
    [
        (
            "UPDATE external_channel_resource_provisionings "
            "SET status = 'pending' WHERE id = 'replace-provisioning'",
            "resource_provisioning_inflight=1",
        ),
        (
            "UPDATE external_channel_invocation_batches "
            "SET wake_dispatch_status = 'pending' WHERE id = 'replace-batch'",
            "invocation_wake_undispatched=1",
        ),
    ],
)
def test_replacement_blocks_inflight_legacy_state_before_ddl(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
    update_sql: str,
    expected_error: str,
) -> None:
    """Reject unsafe cutover without exposing row or provider identity."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_parent_graph(connection)
        connection.execute(sa.text(update_sql))

    with pytest.raises(RuntimeError) as error:
        alembic_runner.migrate_up_to(_REVISION)

    message = str(error.value)
    assert expected_error in message
    assert "replace-provisioning" not in message
    assert "replace-batch" not in message
    assert "replace-channel" not in message
    inspector = sa.inspect(alembic_engine)
    assert _RETIRED_TABLES <= set(inspector.get_table_names())
    assert "source_message_id" in _column_names(
        inspector,
        "external_channel_access_requests",
    )


def test_replacement_blocks_duplicate_open_selector_identity_before_ddl(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Reject legacy selectors that converge on one retained interaction key."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_parent_graph(connection)
        connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_resources (
                    id, connection_id, resource_type, provider_resource_key,
                    labels, status
                )
                VALUES (
                    'duplicate-resource', 'replace-connection', 'thread',
                    'slack:replace-tenant:replace-channel:2.000002',
                    '{"thread_ts": "2.000002"}'::jsonb, 'active'
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_messages (
                    id, resource_id, provider_message_key, provider_position,
                    lifecycle, author_type, principal_id
                )
                VALUES (
                    'duplicate-message', 'duplicate-resource',
                    'slack:replace-tenant:replace-channel:1.000001',
                    '00000000000000000002.000002', 'current', 'human',
                    'replace-principal'
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_conversation_admissions (
                    id, connection_id, resource_id, source_message_id, origin,
                    status, expires_at, initiating_principal_id,
                    conversation_position_id, range_start_position,
                    trigger_position
                )
                VALUES (
                    'duplicate-admission', 'replace-connection',
                    'duplicate-resource', 'duplicate-message',
                    'mention_selector', 'pending_selection',
                    now() + interval '1 hour', 'replace-principal',
                    'replace-position', '00000000000000000000.000000',
                    '00000000000000000002.000002'
                )
                """
            )
        )

    with pytest.raises(RuntimeError) as error:
        alembic_runner.migrate_up_to(_REVISION)

    message = str(error.value)
    assert "selector_key_collisions=1" in message
    assert "duplicate-admission" not in message
    assert "replace-channel" not in message
    inspector = sa.inspect(alembic_engine)
    assert _RETIRED_TABLES <= set(inspector.get_table_names())


def test_replacement_blocks_malformed_open_selector_identity_before_ddl(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Reject an open selector whose provider key cannot be replayed."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_parent_graph(connection)
        connection.execute(
            sa.text(
                """
                UPDATE external_channel_messages
                SET provider_message_key = 'slack:other-tenant:replace-channel:1.000001'
                WHERE id = 'replace-message'
                """
            )
        )

    with pytest.raises(RuntimeError) as error:
        alembic_runner.migrate_up_to(_REVISION)

    message = str(error.value)
    assert "selector_rows_invalid=1" in message
    assert "other-tenant" not in message
    assert "replace-channel" not in message
    inspector = sa.inspect(alembic_engine)
    assert _RETIRED_TABLES <= set(inspector.get_table_names())


def test_replacement_blocks_data_bearing_downgrade(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Do not recreate empty legacy owners while retained access rows exist."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_parent_graph(connection)
    alembic_runner.migrate_up_to(_REVISION)

    with pytest.raises(RuntimeError) as error:
        alembic_runner.migrate_down_to(_PARENT_REVISION)

    assert "external_channel_access_requests_prevent_downgrade=1" in str(error.value)
    assert "replace-access" not in str(error.value)
    inspector = sa.inspect(alembic_engine)
    assert _RETIRED_TABLES.isdisjoint(inspector.get_table_names())


def test_replacement_allows_empty_structural_downgrade(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Restore only an empty legacy schema when no retained replay row exists."""
    alembic_runner.migrate_up_to(_REVISION)
    alembic_runner.migrate_down_to(_PARENT_REVISION)

    inspector = sa.inspect(alembic_engine)
    assert _RETIRED_TABLES <= set(inspector.get_table_names())
    assert "source_message_id" in _column_names(
        inspector,
        "external_channel_access_requests",
    )
    assert "trigger_provider_message_key" not in _column_names(
        inspector,
        "external_channel_access_requests",
    )
    with alembic_engine.connect() as connection:
        assert _RETIRED_ENUMS <= _enum_names(connection)
