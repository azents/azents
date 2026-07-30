"""Migration-specific tests for External Channel legacy contraction."""

from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT_REVISION = "acd4e70d9c19"
_REVISION = "f1a13c6dc46d"


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    """Return the reflected column names for one table."""
    return {column["name"] for column in inspector.get_columns(table)}


def _constraint_names(
    constraints: Sequence[Mapping[str, object]],
) -> set[str]:
    """Return non-null reflected constraint names."""
    return {
        name
        for constraint in constraints
        if isinstance((name := constraint.get("name")), str)
    }


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


def _insert_workspace_and_connection(connection: sa.Connection) -> None:
    """Insert the minimum parent graph for a legacy event."""
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('workspace-sensitive-id', 'W', 'contraction-w')
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
                'connection-sensitive-id', 'workspace-sensitive-id', 'slack',
                'http', 'slack_http', 'active', 'single', 'A1', 'T1'
            )
            """
        )
    )


def _insert_agent(connection: sa.Connection) -> None:
    """Insert one parent-revision Agent with valid model metadata."""
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id, workspace_id, name, model_selection, lightweight_model_selection,
                selectable_model_options, main_model_label, lightweight_model_label
            )
            VALUES (
                'agent-sensitive-id', 'workspace-sensitive-id', 'Agent',
                '{}'::jsonb, '{}'::jsonb,
                '[
                    {"label": "contraction-main", "model_selection": {}},
                    {"label": "contraction-light", "model_selection": {}}
                ]'::jsonb,
                'contraction-main', 'contraction-light'
            )
            """
        )
    )


def _insert_active_binding_without_batch(connection: sa.Connection) -> None:
    """Insert one otherwise-qualified active binding without an accepted batch."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO users (id, primary_email_id)
            VALUES ('user-sensitive-id', 'email-sensitive-id')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO user_emails (id, user_id, email, verified_at)
            VALUES (
                'email-sensitive-id', 'user-sensitive-id',
                'contraction@example.com', now()
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO workspace_users (
                id, workspace_id, user_id, name, role
            )
            VALUES (
                'workspace-user-sensitive-id', 'workspace-sensitive-id',
                'user-sensitive-id', 'Contraction User', 'owner'
            )
            """
        )
    )
    _insert_agent(connection)
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status, start_reason,
                session_kind
            )
            VALUES (
                'session-sensitive-id', 'workspace-sensitive-id',
                'agent-sensitive-id', 'contraction-s', 'active',
                'external_channel', 'root'
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
                'route-sensitive-id', 'connection-sensitive-id',
                'agent-sensitive-id', 'agent-sensitive-id', 'dedicated',
                'single', 'available'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_resources (
                id, connection_id, resource_type, provider_resource_key,
                status, hydration_status
            )
            VALUES (
                'resource-sensitive-id', 'connection-sensitive-id', 'thread',
                'slack:T1:C1:1.000001', 'active', 'complete'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_messages (
                id, resource_id, provider_message_key, provider_position,
                lifecycle, author_type
            )
            VALUES (
                'message-sensitive-id', 'resource-sensitive-id',
                'slack:T1:C1:1.000001', '1.000001', 'current', 'human'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_bindings (
                id, resource_id, route_id, agent_session_id, status,
                activation_status
            )
            VALUES (
                'binding-sensitive-id', 'resource-sensitive-id',
                'route-sensitive-id', 'session-sensitive-id', 'active', 'active'
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
                'position-sensitive-id', 'connection-sensitive-id', 'thread',
                'C1', '1.000001', '1.000001'
            )
            """
        )
    )


def _insert_accepted_batch(connection: sa.Connection) -> None:
    """Complete the retained active-binding ownership graph."""
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_invocation_batches (
                id, binding_id, trigger_message_id, first_provider_position,
                last_provider_position, connection_id,
                conversation_position_id, range_start_position,
                trigger_position, context_omitted, wake_dispatch_status
            )
            VALUES (
                'batch-sensitive-id', 'binding-sensitive-id',
                'message-sensitive-id', '1.000001', '1.000001',
                'connection-sensitive-id', 'position-sensitive-id',
                NULL, '1.000001', false, 'dispatched'
            )
            """
        )
    )


def test_contraction_aborts_before_ddl_for_undrained_events(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Reject nonterminal event backlog with content-free diagnostics."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _insert_workspace_and_connection(connection)
        connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_events (
                    id, connection_id, provider_event_id, event_type, envelope
                )
                VALUES (
                    'event-sensitive-id', 'connection-sensitive-id',
                    'provider-sensitive-id', 'app_mention',
                    '{"content": "private-sensitive-content"}'::jsonb
                )
                """
            )
        )

    try:
        alembic_runner.migrate_up_to(_REVISION)
    except RuntimeError as error:
        message = str(error)
    else:
        raise AssertionError("Contraction unexpectedly accepted legacy event backlog.")

    assert "events_undrained=1" in message
    assert "event-sensitive-id" not in message
    assert "provider-sensitive-id" not in message
    assert "private-sensitive-content" not in message
    inspector = sa.inspect(alembic_engine)
    assert "external_channel_events" in inspector.get_table_names()
    assert "source_event_id" in _column_names(
        inspector,
        "external_channel_message_revisions",
    )


def test_contraction_rechecks_active_binding_ownership(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Reject an active binding without a latest accepted invocation batch."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _insert_workspace_and_connection(connection)
        _insert_active_binding_without_batch(connection)

    try:
        alembic_runner.migrate_up_to(_REVISION)
    except RuntimeError as error:
        message = str(error)
    else:
        raise AssertionError("Contraction unexpectedly accepted incomplete ownership.")

    assert "active_bindings_without_latest_batch=1" in message
    assert "binding-sensitive-id" not in message
    assert "resource-sensitive-id" not in message
    assert "session-sensitive-id" not in message


def test_contraction_classifies_duplicate_thread_positions_as_ambiguous(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Reject duplicate scope rows as ambiguity even when one position is null."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _insert_workspace_and_connection(connection)
        _insert_active_binding_without_batch(connection)
        _insert_accepted_batch(connection)
        connection.execute(
            sa.text("DROP INDEX uq_external_channel_conversation_positions_thread")
        )
        connection.execute(
            sa.text(
                """
                UPDATE external_channel_conversation_positions
                SET read_through_position = NULL
                WHERE id = 'position-sensitive-id'
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
                    'position-sensitive-duplicate',
                    'connection-sensitive-id', 'thread',
                    'C1', '1.000001', '1.000001'
                )
                """
            )
        )

    try:
        alembic_runner.migrate_up_to(_REVISION)
    except RuntimeError as error:
        message = str(error)
    else:
        raise AssertionError("Contraction unexpectedly accepted ambiguous positions.")

    assert "active_bindings_with_ambiguous_thread_position=1" in message
    assert "active_bindings_without_thread_position" not in message
    assert "position-sensitive-id" not in message
    assert "position-sensitive-duplicate" not in message


def test_contraction_ddl_and_structural_downgrade(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Remove legacy state and restore only its empty structural shape on downgrade."""
    alembic_runner.migrate_up_to(_REVISION)
    inspector = sa.inspect(alembic_engine)

    assert "external_channel_events" not in inspector.get_table_names()
    assert "external_channel_pending_contexts" not in inspector.get_table_names()
    assert {
        "hydration_status",
        "hydration_cursor",
        "hydration_high_watermark_position",
        "reconciliation_boundary_received_at",
        "reconciliation_boundary_event_id",
        "hydration_error_kind",
        "hydration_error_summary",
        "hydration_started_at",
        "hydration_completed_at",
    }.isdisjoint(_column_names(inspector, "external_channel_resources"))
    assert {
        "activation_status",
        "activation_trigger_message_id",
        "activated_at",
        "activation_wake_claimed_at",
        "projected_through_position",
        "truncated_message_count",
        "truncated_size",
    }.isdisjoint(_column_names(inspector, "external_channel_bindings"))
    assert {
        "truncation_message_count",
        "truncation_size",
    }.isdisjoint(_column_names(inspector, "external_channel_invocation_batches"))
    assert "source_event_id" not in _column_names(
        inspector,
        "external_channel_message_revisions",
    )
    assert {
        "ck_external_channel_conversation_admissions_open_boundary"
    } <= _constraint_names(
        inspector.get_check_constraints("external_channel_conversation_admissions")
    )
    assert {
        "ck_external_channel_access_requests_pending_boundary"
    } <= _constraint_names(
        inspector.get_check_constraints("external_channel_access_requests")
    )
    with alembic_engine.connect() as connection:
        assert {
            "external_channel_event_eligibility_state",
            "external_channel_event_status",
            "external_channel_hydration_status",
            "external_channel_binding_activation_status",
        }.isdisjoint(_enum_names(connection))

    alembic_runner.migrate_down_to(_PARENT_REVISION)
    inspector = sa.inspect(alembic_engine)
    assert "external_channel_events" in inspector.get_table_names()
    assert "external_channel_pending_contexts" in inspector.get_table_names()
    assert "hydration_status" in _column_names(
        inspector,
        "external_channel_resources",
    )
    assert "activation_status" in _column_names(
        inspector,
        "external_channel_bindings",
    )
    assert "truncation_message_count" in _column_names(
        inspector,
        "external_channel_invocation_batches",
    )
    assert "source_event_id" in _column_names(
        inspector,
        "external_channel_message_revisions",
    )
    assert "ck_external_channel_conversation_admissions_open_boundary" not in (
        _constraint_names(
            inspector.get_check_constraints("external_channel_conversation_admissions")
        )
    )
    assert "ck_external_channel_access_requests_pending_boundary" not in (
        _constraint_names(
            inspector.get_check_constraints("external_channel_access_requests")
        )
    )
    with alembic_engine.connect() as connection:
        assert {
            "external_channel_event_eligibility_state",
            "external_channel_event_status",
            "external_channel_hydration_status",
            "external_channel_binding_activation_status",
        } <= _enum_names(connection)
        assert (
            connection.execute(
                sa.text("SELECT count(*) FROM external_channel_events")
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                sa.text("SELECT count(*) FROM external_channel_pending_contexts")
            ).scalar_one()
            == 0
        )
