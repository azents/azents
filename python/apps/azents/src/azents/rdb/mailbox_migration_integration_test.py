"""Docker-backed integration coverage for the mailbox persistence migration."""

from collections.abc import Generator

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from azcommon.testing.images import get_docker_hub_image
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "cc31dfa97a1b"
_MAILBOX_REVISION = "8bbe580fddad"


def _migration_database() -> Generator[tuple[AlembicConfig, sa.Engine], None, None]:
    """Create an isolated PostgreSQL database for migration verification."""
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


def _seed_identity_graph(connection: sa.Connection) -> None:
    """Seed the minimum tenant, Agent, Session, and User graph."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO users (id, primary_email_id)
            VALUES ('user-mailbox-migration', 'email-mailbox-migration')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO user_emails (id, user_id, email, verified_at)
            VALUES (
                'email-mailbox-migration',
                'user-mailbox-migration',
                'mailbox-migration@example.com',
                now()
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES (
                'workspace-mailbox-migration',
                'Mailbox migration',
                'mailbox-migration'
            )
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
                'agent-mailbox-migration',
                'workspace-mailbox-migration',
                'Mailbox migration Agent',
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
                id, workspace_id, agent_id, handle, status, start_reason, session_kind
            )
            VALUES (
                'session-mailbox-migration',
                'workspace-mailbox-migration',
                'agent-mailbox-migration',
                'mailbox-migration-session',
                'active',
                'initial',
                'root'
            )
            """
        )
    )


def _seed_external_graph(connection: sa.Connection) -> None:
    """Seed one valid two-item External Channel invocation batch."""
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_connections (
                id, workspace_id, provider, transport, status, provider_app_id,
                provider_tenant_id, encrypted_credentials
            )
            VALUES (
                'connection-mailbox-migration',
                'workspace-mailbox-migration',
                'slack',
                'http',
                'active',
                'migration-app',
                'migration-tenant',
                'migration-ciphertext'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_agent_routes (
                id, connection_id, agent_id, agent_id_snapshot, route_mode,
                connection_app_mode
            )
            VALUES (
                'route-mailbox-migration',
                'connection-mailbox-migration',
                'agent-mailbox-migration',
                'agent-mailbox-migration',
                'dedicated',
                'single'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_resources (
                id, connection_id, resource_type, provider_resource_key, status,
                labels
            )
            VALUES (
                'resource-mailbox-migration',
                'connection-mailbox-migration',
                'thread',
                'slack:migration-tenant:C-MIGRATION:1.000001',
                'active',
                '{"channel_id":"C-MIGRATION","channel_name":"migration"}'::jsonb
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_principals (
                id, provider, provider_tenant_id, provider_user_id, author_type,
                display_name
            )
            VALUES (
                'principal-mailbox-migration',
                'slack',
                'migration-tenant',
                'U-MIGRATION',
                'human',
                'Migration User'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_messages (
                id, resource_id, provider_message_key, provider_position, lifecycle,
                author_type, principal_id
            )
            VALUES
                (
                    'message-mailbox-context',
                    'resource-mailbox-migration',
                    'slack:migration-context',
                    '1.000001',
                    'current',
                    'human',
                    'principal-mailbox-migration'
                ),
                (
                    'message-mailbox-trigger',
                    'resource-mailbox-migration',
                    'slack:migration-trigger',
                    '1.000002',
                    'current',
                    'human',
                    'principal-mailbox-migration'
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
            VALUES
                (
                    'revision-mailbox-context',
                    'message-mailbox-context',
                    'v1',
                    'original',
                    'Context from migration',
                    '{}'::jsonb,
                    '{}'::jsonb
                ),
                (
                    'revision-mailbox-trigger',
                    'message-mailbox-trigger',
                    'v1',
                    'original',
                    'Trigger from migration',
                    '{}'::jsonb,
                    '{}'::jsonb
                )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE external_channel_messages
            SET current_revision_id = CASE id
                WHEN 'message-mailbox-context' THEN 'revision-mailbox-context'
                WHEN 'message-mailbox-trigger' THEN 'revision-mailbox-trigger'
            END
            WHERE id IN ('message-mailbox-context', 'message-mailbox-trigger')
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
                'binding-mailbox-migration',
                'resource-mailbox-migration',
                'route-mailbox-migration',
                'session-mailbox-migration',
                'active'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_invocation_batches (
                id, binding_id, trigger_message_id, first_provider_position,
                last_provider_position, truncation_message_count, truncation_size,
                input_buffer_id
            )
            VALUES (
                'batch-mailbox-migration',
                'binding-mailbox-migration',
                'message-mailbox-trigger',
                '1.000001',
                '1.000002',
                0,
                0,
                'mailbox-external-migration'
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
            VALUES
                (
                    'batch-item-mailbox-context',
                    'batch-mailbox-migration',
                    'revision-mailbox-context',
                    0,
                    '1.000001'
                ),
                (
                    'batch-item-mailbox-trigger',
                    'batch-mailbox-migration',
                    'revision-mailbox-trigger',
                    1,
                    '1.000002'
                )
            """
        )
    )


def _seed_mailbox_rows(connection: sa.Connection) -> None:
    """Seed one pre-mailbox row for every typed kind."""
    rows = [
        (
            "mailbox-user-migration",
            "user_message",
            "wake_session",
            "user-mailbox-migration",
            "User migration",
            None,
            "user-migration",
        ),
        (
            "mailbox-goal-migration",
            "goal_continuation",
            "wake_session",
            None,
            "Goal migration",
            None,
            "goal-migration",
        ),
        (
            "mailbox-agent-migration",
            "agent_message",
            "queue_only",
            None,
            "Agent migration",
            None,
            "agent-migration",
        ),
        (
            "mailbox-action-migration",
            "action_message",
            "wake_session",
            "user-mailbox-migration",
            "Action migration",
            '{"type":"command","name":"compact"}',
            "action-migration",
        ),
        (
            "mailbox-external-migration",
            "external_channel_invocation",
            "wake_session",
            None,
            "External migration",
            None,
            "external-migration",
        ),
    ]
    for row in rows:
        connection.execute(
            sa.text(
                """
                INSERT INTO input_buffers (
                    id, session_id, kind, scheduling_mode,
                    requested_model_target_label, requested_reasoning_effort,
                    sender_user_id, content, idempotency_key, metadata, action,
                    attachments, file_parts
                )
                VALUES (
                    :id,
                    'session-mailbox-migration',
                    :kind,
                    :scheduling_mode,
                    'default',
                    NULL,
                    :sender_user_id,
                    :content,
                    :idempotency_key,
                    '{}'::jsonb,
                    CAST(:action AS jsonb),
                    '[]'::jsonb,
                    '[]'::jsonb
                )
                """
            ),
            {
                "id": row[0],
                "kind": row[1],
                "scheduling_mode": row[2],
                "sender_user_id": row[3],
                "content": row[4],
                "action": row[5],
                "idempotency_key": row[6],
            },
        )


def _seed_valid_database(connection: sa.Connection) -> None:
    """Seed identity, every pre-mailbox kind, and External Channel graph."""
    _seed_identity_graph(connection)
    _seed_mailbox_rows(connection)
    _seed_external_graph(connection)


def test_mailbox_migration_upgrades_all_kinds_and_downgrades_cleanly(
    check_docker_availability: None,
) -> None:
    """Upgrade every kind and preserve compound External Channel ordering."""
    del check_docker_availability
    database = _migration_database()
    config, engine = next(database)
    try:
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_valid_database(connection)

        alembic_command.upgrade(config, _MAILBOX_REVISION)
        with engine.connect() as connection:
            rows = (
                connection.execute(
                    sa.text(
                        """
                    SELECT id, kind::text AS kind, payload
                    FROM mailbox_items
                    ORDER BY id
                    """
                    )
                )
                .mappings()
                .all()
            )
            assert {row["kind"] for row in rows} == {
                "user_message",
                "goal_continuation",
                "agent_message",
                "action_message",
                "external_channel_invocation",
            }
            assert all(row["payload"] is not None for row in rows)
            external = next(
                row for row in rows if row["kind"] == "external_channel_invocation"
            )
            assert [item["item_key"] for item in external["payload"]["items"]] == [
                "external_channel:0",
                "external_channel:1",
            ]
            assert [item["content"] for item in external["payload"]["items"]] == [
                "Context from migration",
                "Trigger from migration",
            ]
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT mailbox_item_id "
                        "FROM external_channel_invocation_batches "
                        "WHERE id = 'batch-mailbox-migration'"
                    )
                )
                == "mailbox-external-migration"
            )

        alembic_command.downgrade(config, _PARENT_REVISION)
        with engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT to_regclass('public.input_buffers')"))
                == "input_buffers"
            )
            assert connection.scalar(sa.text("SELECT count(*) FROM input_buffers")) == 5
    finally:
        database.close()


def test_mailbox_migration_rejects_unresolvable_external_row(
    check_docker_availability: None,
) -> None:
    """Reject an External Channel row without a batch before dropping legacy columns."""
    del check_docker_availability
    database = _migration_database()
    config, engine = next(database)
    try:
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_identity_graph(connection)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO input_buffers (
                        id, session_id, kind, scheduling_mode,
                        requested_model_target_label, requested_reasoning_effort,
                        sender_user_id, content, idempotency_key, metadata, action,
                        attachments, file_parts
                    )
                    VALUES (
                        'mailbox-invalid-external',
                        'session-mailbox-migration',
                        'external_channel_invocation',
                        'wake_session',
                        'default',
                        NULL,
                        NULL,
                        'Invalid external migration',
                        'invalid-external',
                        '{}'::jsonb,
                        NULL,
                        '[]'::jsonb,
                        '[]'::jsonb
                    )
                    """
                )
            )

        with pytest.raises((DBAPIError, ValueError)):
            alembic_command.upgrade(config, _MAILBOX_REVISION)

        with engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT to_regclass('public.input_buffers')"))
                == "input_buffers"
            )
            columns = {
                row["column_name"]
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'input_buffers'
                        """
                    )
                ).mappings()
            }
            assert {"content", "metadata", "attachments", "file_parts"} <= columns
    finally:
        database.close()
