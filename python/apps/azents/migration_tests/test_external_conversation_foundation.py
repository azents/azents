"""Migration-specific tests for external conversation position backfill."""

from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT_REVISION = "cb091fe69575"
_REVISION = "acd4e70d9c19"


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


def _insert_agent(
    connection: sa.Connection,
    *,
    agent_id: str,
    workspace_id: str,
) -> None:
    """Insert one parent-revision Agent with valid model metadata."""
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id, workspace_id, name, model_selection, lightweight_model_selection,
                selectable_model_options, main_model_label, lightweight_model_label
            )
            VALUES (
                :agent_id, :workspace_id, :agent_id, '{}'::jsonb, '{}'::jsonb,
                '[
                    {"label": "foundation-main", "model_selection": {}},
                    {"label": "foundation-lightweight", "model_selection": {}}
                ]'::jsonb,
                'foundation-main', 'foundation-lightweight'
            )
            """
        ),
        {"agent_id": agent_id, "workspace_id": workspace_id},
    )


def _seed_parent_graph(connection: sa.Connection) -> None:
    """Seed one FK-valid active Slack thread at the current parent revision."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO users (id, primary_email_id)
            VALUES ('u', 'email-u')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO user_emails (id, user_id, email, verified_at)
            VALUES ('email-u', 'u', 'foundation@example.com', now())
            """
        )
    )
    connection.execute(
        sa.text("INSERT INTO workspaces (id, name, handle) VALUES ('w', 'W', 'w')")
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO workspace_users (id, workspace_id, user_id, name, role)
            VALUES ('wu', 'w', 'u', 'Foundation User', 'owner')
            """
        )
    )
    _insert_agent(connection, agent_id="a", workspace_id="w")
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status, start_reason, session_kind
            )
            VALUES (
                's', 'w', 'a', 's', 'active', 'external_channel', 'root'
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
                'c', 'w', 'slack', 'http', 'slack_http', 'active', 'single',
                'A1', 'T1'
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
                'route', 'c', 'a', 'a', 'dedicated', 'single', 'available'
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
                'resource', 'c', 'thread', 'slack:T1:C1:1.000001', 'active'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_messages (
                id, resource_id, provider_message_key, provider_position, lifecycle,
                author_type
            )
            VALUES (
                'message', 'resource', 'slack:T1:C1:1.000001', '1.000001',
                'current', 'human'
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
                'binding', 'resource', 'route', 's', 'active', 'active'
            )
            """
        )
    )


def _prepare_parent(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
    *,
    projected: str | None,
    batch: bool,
) -> None:
    """Upgrade to the parent and seed one recoverable or invalid binding."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_parent_graph(connection)
        if projected is not None:
            connection.execute(
                sa.text(
                    "UPDATE external_channel_bindings "
                    "SET projected_through_position = :position WHERE id = 'binding'"
                ),
                {"position": projected},
            )
        if batch:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO external_channel_invocation_batches
                        (id, binding_id, trigger_message_id, first_provider_position,
                         last_provider_position)
                    VALUES ('batch', 'binding', 'message', '1.000001', '1.000009')
                    """
                )
            )


def test_backfill_prefers_projected_boundary(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Backfill the active thread from its retained projection boundary."""
    _prepare_parent(
        alembic_runner,
        alembic_engine,
        projected="1.000010",
        batch=False,
    )
    alembic_runner.migrate_up_to(_REVISION)

    with alembic_engine.connect() as connection:
        assert (
            connection.execute(
                sa.text(
                    "SELECT read_through_position FROM "
                    "external_channel_conversation_positions"
                )
            ).scalar_one()
            == "1.000010"
        )


def test_backfill_uses_latest_invocation_boundary(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Fall back to the latest accepted invocation boundary."""
    _prepare_parent(
        alembic_runner,
        alembic_engine,
        projected=None,
        batch=True,
    )
    alembic_runner.migrate_up_to(_REVISION)

    with alembic_engine.connect() as connection:
        assert (
            connection.execute(
                sa.text(
                    "SELECT read_through_position FROM "
                    "external_channel_conversation_positions"
                )
            ).scalar_one()
            == "1.000009"
        )


def test_backfill_aborts_without_identifiers(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Abort with aggregate-only diagnostics when no boundary is recoverable."""
    _prepare_parent(
        alembic_runner,
        alembic_engine,
        projected=None,
        batch=False,
    )

    try:
        alembic_runner.migrate_up_to(_REVISION)
    except RuntimeError as error:
        message = str(error)
    else:
        raise AssertionError("Foundation migration unexpectedly accepted no boundary.")

    assert "unrecoverable_active_position_count=1" in message
    assert "binding" not in message
    assert "resource" not in message


def test_foundation_ddl_contract(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Require the Foundation revision's complete PostgreSQL DDL contract."""
    alembic_runner.migrate_up_to(_REVISION)
    inspector = sa.inspect(alembic_engine)

    assert _column_names(
        inspector,
        "external_channel_conversation_positions",
    ) == {
        "id",
        "connection_id",
        "scope_kind",
        "provider_channel_id",
        "provider_thread_key",
        "read_through_position",
        "created_at",
        "updated_at",
    }
    assert {
        "conversation_position_id",
        "range_start_position",
        "trigger_position",
    } <= _column_names(inspector, "external_channel_conversation_admissions")
    assert {
        "connection_id",
        "conversation_position_id",
        "range_start_position",
        "trigger_position",
        "context_omitted",
        "wake_dispatch_status",
        "wake_dispatch_claimed_at",
    } <= _column_names(inspector, "external_channel_invocation_batches")
    assert {
        "connection_id",
        "conversation_position_id",
        "range_start_position",
        "trigger_position",
    } <= _column_names(inspector, "external_channel_access_requests")

    position_indexes = _constraint_names(
        inspector.get_indexes("external_channel_conversation_positions")
    )
    assert {
        "uq_external_channel_conversation_positions_parent",
        "uq_external_channel_conversation_positions_thread",
    } <= position_indexes
    assert {
        "uq_external_channel_conversation_positions_connection_id_id"
    } <= _constraint_names(
        inspector.get_unique_constraints("external_channel_conversation_positions")
    )
    assert {
        "ck_external_channel_conversation_positions_scope_key"
    } <= _constraint_names(
        inspector.get_check_constraints("external_channel_conversation_positions")
    )

    assert {
        "fk_external_channel_conv_admissions_connection_position"
    } <= _constraint_names(
        inspector.get_foreign_keys("external_channel_conversation_admissions")
    )
    assert {
        "fk_external_channel_invocation_batches_conversation_position"
    } <= _constraint_names(
        inspector.get_foreign_keys("external_channel_invocation_batches")
    )
    assert {
        "fk_external_channel_access_requests_connection_resource",
        "fk_external_channel_access_requests_connection_position",
    } <= _constraint_names(
        inspector.get_foreign_keys("external_channel_access_requests")
    )

    with alembic_engine.connect() as connection:
        enum_values = connection.execute(
            sa.text(
                """
                SELECT type.typname, enum.enumlabel
                FROM pg_type AS type
                JOIN pg_enum AS enum ON enum.enumtypid = type.oid
                WHERE type.typname IN (
                    'external_channel_conversation_scope_kind',
                    'external_channel_invocation_wake_dispatch_status'
                )
                ORDER BY type.typname, enum.enumsortorder
                """
            )
        ).all()
        defaults = {
            str(row["column_name"]): str(row["column_default"])
            for row in connection.execute(
                sa.text(
                    """
                    SELECT column_name, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'external_channel_invocation_batches'
                      AND column_name IN ('context_omitted', 'wake_dispatch_status')
                    """
                )
            ).mappings()
        }

    assert enum_values == [
        ("external_channel_conversation_scope_kind", "parent_channel"),
        ("external_channel_conversation_scope_kind", "thread"),
        ("external_channel_invocation_wake_dispatch_status", "pending"),
        ("external_channel_invocation_wake_dispatch_status", "claimed"),
        ("external_channel_invocation_wake_dispatch_status", "dispatched"),
    ]
    assert defaults["context_omitted"] == "false"
    assert "dispatched" in defaults["wake_dispatch_status"]
