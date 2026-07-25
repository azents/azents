"""Migration integration tests for Team Session admission provenance."""

import json
from collections.abc import Generator

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from azcommon.testing.images import get_docker_hub_image
from sqlalchemy.exc import IntegrityError
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "995d915ed6d6"
_PROVENANCE_REVISION = "1ce295000a20"
_USER_ID = "user-migration"
_EMAIL_ID = "email-migration"
_WORKSPACE_ID = "workspace-migration"
_AGENT_ID = "agent-migration"
_SESSION_ID = "session-migration"
_INPUT_BUFFER_ID = "input-buffer-migration"
_ACTION_EXECUTION_ID = "action-execution-migration"


def _migration_database() -> Generator[tuple[AlembicConfig, sa.Engine], None, None]:
    """Create an isolated PostgreSQL database for one migration test."""
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


def _seed_legacy_graph(connection: sa.Connection) -> None:
    """Seed valid parent-revision rows that carry legacy provenance columns."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO users (id, primary_email_id)
            VALUES (:user_id, :email_id)
            """
        ),
        {"user_id": _USER_ID, "email_id": _EMAIL_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO user_emails (id, user_id, email, verified_at)
            VALUES (:email_id, :user_id, 'migration@example.com', now())
            """
        ),
        {"user_id": _USER_ID, "email_id": _EMAIL_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES (:workspace_id, 'Migration workspace', 'migration-workspace')
            """
        ),
        {"workspace_id": _WORKSPACE_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO workspace_users (id, workspace_id, user_id, name, role)
            VALUES (
                'workspace-user-migration',
                :workspace_id,
                :user_id,
                'Migration User',
                'owner'
            )
            """
        ),
        {"workspace_id": _WORKSPACE_ID, "user_id": _USER_ID},
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
                :agent_id,
                :workspace_id,
                'Migration Agent',
                '{}'::jsonb,
                '{}'::jsonb,
                '[
                    {
                        "label": "migration-main",
                        "model_selection": {}
                    },
                    {
                        "label": "migration-lightweight",
                        "model_selection": {}
                    }
                ]'::jsonb,
                'migration-main',
                'migration-lightweight'
            )
            """
        ),
        {"agent_id": _AGENT_ID, "workspace_id": _WORKSPACE_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id,
                workspace_id,
                agent_id,
                handle,
                status,
                start_reason,
                session_kind,
                pending_command_id,
                pending_command_name,
                pending_command_payload,
                pending_command_user_id,
                pending_command_created_at,
                stop_requested_at,
                stop_requested_by,
                stop_request_id
            )
            VALUES (
                :session_id,
                :workspace_id,
                :agent_id,
                'migration-session',
                'active',
                'initial',
                'root',
                'pending-command-migration',
                'resume',
                '{}'::jsonb,
                :user_id,
                now(),
                now(),
                :user_id,
                'stop-request-migration'
            )
            """
        ),
        {
            "agent_id": _AGENT_ID,
            "session_id": _SESSION_ID,
            "user_id": _USER_ID,
            "workspace_id": _WORKSPACE_ID,
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO input_buffers (
                id,
                session_id,
                kind,
                scheduling_mode,
                requested_model_target_label,
                requested_reasoning_effort,
                actor_user_id,
                content,
                idempotency_key,
                metadata,
                action,
                attachments,
                file_parts
            )
            VALUES (
                :input_buffer_id,
                :session_id,
                'user_message',
                'wake_session',
                NULL,
                NULL,
                :user_id,
                'Legacy Human message',
                'migration-input',
                '{}'::jsonb,
                NULL,
                '[]'::jsonb,
                '[]'::jsonb
            )
            """
        ),
        {
            "input_buffer_id": _INPUT_BUFFER_ID,
            "session_id": _SESSION_ID,
            "user_id": _USER_ID,
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO chat_write_requests (
                id,
                session_id,
                user_id,
                client_request_id,
                write_type,
                accepted_type,
                accepted_id,
                history_reload_required,
                payload
            )
            VALUES (
                'chat-write-migration',
                :session_id,
                :user_id,
                'migration-client-request',
                'command',
                'command',
                'pending-command-migration',
                false,
                '{}'::jsonb
            )
            """
        ),
        {"session_id": _SESSION_ID, "user_id": _USER_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO action_executions (
                id,
                session_id,
                input_buffer_id,
                action_type,
                action,
                owner_generation,
                status,
                failure_summary
            )
            VALUES (
                :action_execution_id,
                :session_id,
                :input_buffer_id,
                'create_git_worktree',
                '{
                    "type": "create_git_worktree",
                    "source_project_path": "/workspace/project",
                    "starting_ref": "main"
                }'::jsonb,
                0,
                'pending',
                NULL
            )
            """
        ),
        {
            "action_execution_id": _ACTION_EXECUTION_ID,
            "input_buffer_id": _INPUT_BUFFER_ID,
            "session_id": _SESSION_ID,
        },
    )
    for model_order, kind in enumerate(
        ("user_message", "goal_continuation", "goal_updated", "action_message"),
        start=1,
    ):
        connection.execute(
            sa.text(
                """
                INSERT INTO events (id, session_id, kind, payload, model_order)
                VALUES (
                    :event_id,
                    :session_id,
                    :kind,
                    CAST(:payload AS jsonb),
                    :model_order
                )
                """
            ),
            {
                "event_id": f"event-migration-{model_order}",
                "kind": kind,
                "model_order": model_order,
                "payload": json.dumps({"content": f"Legacy {kind}"}),
                "session_id": _SESSION_ID,
            },
        )


def _insert_input_buffer(
    connection: sa.Connection,
    *,
    buffer_id: str,
    kind: str,
    sender_user_id: str,
) -> None:
    """Insert one post-migration buffer used to exercise sender constraints."""
    connection.execute(
        sa.text(
            """
            INSERT INTO input_buffers (
                id,
                session_id,
                kind,
                scheduling_mode,
                requested_model_target_label,
                requested_reasoning_effort,
                sender_user_id,
                content,
                idempotency_key,
                metadata,
                action,
                attachments,
                file_parts
            )
            VALUES (
                :buffer_id,
                :session_id,
                :kind,
                'wake_session',
                NULL,
                NULL,
                :sender_user_id,
                'Constraint probe',
                :buffer_id,
                '{}'::jsonb,
                NULL,
                '[]'::jsonb,
                '[]'::jsonb
            )
            """
        ),
        {
            "buffer_id": buffer_id,
            "kind": kind,
            "sender_user_id": sender_user_id,
            "session_id": _SESSION_ID,
        },
    )


def test_team_session_admission_provenance_migration(
    check_docker_availability: None,
) -> None:
    """Upgrade legacy admission rows and verify Phase 1 provenance contracts."""
    del check_docker_availability
    migration_database = _migration_database()
    config, engine = next(migration_database)
    try:
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_legacy_graph(connection)

        alembic_command.upgrade(config, _PROVENANCE_REVISION)

        with engine.connect() as connection:
            input_buffer_sender = connection.scalar(
                sa.text(
                    """
                    SELECT sender_user_id
                    FROM input_buffers
                    WHERE id = :input_buffer_id
                    """
                ),
                {"input_buffer_id": _INPUT_BUFFER_ID},
            )
            chat_write_requester = connection.scalar(
                sa.text(
                    """
                    SELECT requester_user_id
                    FROM chat_write_requests
                    WHERE id = 'chat-write-migration'
                    """
                )
            )
            session_provenance = connection.execute(
                sa.text(
                    """
                    SELECT
                        pending_command_requester_user_id,
                        stop_requester_user_id
                    FROM agent_sessions
                    WHERE id = :session_id
                    """
                ),
                {"session_id": _SESSION_ID},
            ).one()
            action_sender = connection.scalar(
                sa.text(
                    """
                    SELECT sender_user_id
                    FROM action_executions
                    WHERE id = :action_execution_id
                    """
                ),
                {"action_execution_id": _ACTION_EXECUTION_ID},
            )
            event_payloads = {
                row.kind: row.payload
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT kind, payload
                        FROM events
                        WHERE session_id = :session_id
                        ORDER BY model_order
                        """
                    ),
                    {"session_id": _SESSION_ID},
                ).mappings()
            }
            input_buffer_columns = set(
                connection.scalars(
                    sa.text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'input_buffers'
                        """
                    )
                )
            )
            chat_write_request_columns = set(
                connection.scalars(
                    sa.text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'chat_write_requests'
                        """
                    )
                )
            )
            chat_write_request_indexes = set(
                connection.scalars(
                    sa.text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE tablename = 'chat_write_requests'
                        """
                    )
                )
            )
            action_sender_nullable = connection.scalar(
                sa.text(
                    """
                    SELECT is_nullable = 'YES'
                    FROM information_schema.columns
                    WHERE table_name = 'action_executions'
                      AND column_name = 'sender_user_id'
                    """
                )
            )
            enum_values = set(
                connection.scalars(
                    sa.text(
                        """
                        SELECT enumlabel
                        FROM pg_enum
                        JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
                        WHERE pg_type.typname = 'chat_write_request_type'
                        """
                    )
                )
            )
            constraints = {
                row.name: row.definition
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT conname AS name, pg_get_constraintdef(oid) AS definition
                        FROM pg_constraint
                        WHERE conrelid IN (
                            'input_buffers'::regclass,
                            'chat_write_requests'::regclass,
                            'agent_sessions'::regclass,
                            'action_executions'::regclass
                        )
                        """
                    )
                ).mappings()
            }

        assert input_buffer_sender == _USER_ID
        assert chat_write_requester == _USER_ID
        assert session_provenance.pending_command_requester_user_id == _USER_ID
        assert session_provenance.stop_requester_user_id == _USER_ID
        assert action_sender is None
        assert input_buffer_columns >= {"sender_user_id"}
        assert "actor_user_id" not in input_buffer_columns
        assert "creation_agent_id" in chat_write_request_columns
        assert (
            "uq_chat_write_requests_creation_agent_requester_client"
            in chat_write_request_indexes
        )
        assert action_sender_nullable is True
        assert {"message", "turn_action"} <= enum_values
        assert set(event_payloads) == {
            "user_message",
            "goal_continuation",
            "goal_updated",
            "action_message",
        }
        assert all(
            payload["sender_user_id"] is None for payload in event_payloads.values()
        )
        assert "fk_input_buffers_sender_user_id_users" in constraints
        assert "ck_input_buffers_sender_user_kind" in constraints
        assert "fk_chat_write_requests_requester_user_id_users" in constraints
        assert "fk_chat_write_requests_creation_agent_id_agents" in constraints
        assert "uq_chat_write_requests_session_requester_client_request" in constraints
        assert (
            "fk_agent_sessions_pending_command_requester_user_id_users" in constraints
        )
        assert "fk_agent_sessions_stop_requester_user_id_users" in constraints
        assert "fk_action_executions_sender_user_id_users" in constraints
        assert "sender_user_id" in constraints["ck_input_buffers_sender_user_kind"]
        assert (
            "requester_user_id"
            in constraints["uq_chat_write_requests_session_requester_client_request"]
        )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                _insert_input_buffer(
                    connection,
                    buffer_id="input-buffer-invalid-kind",
                    kind="goal_continuation",
                    sender_user_id=_USER_ID,
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                _insert_input_buffer(
                    connection,
                    buffer_id="input-buffer-invalid-sender",
                    kind="user_message",
                    sender_user_id="missing-user",
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO chat_write_requests (
                            id,
                            session_id,
                            requester_user_id,
                            client_request_id,
                            write_type,
                            accepted_type,
                            accepted_id,
                            history_reload_required,
                            payload
                        )
                        VALUES (
                            'chat-write-duplicate',
                            :session_id,
                            :requester_user_id,
                            'migration-client-request',
                            'message',
                            'message',
                            'input-buffer-duplicate',
                            false,
                            '{}'::jsonb
                        )
                        """
                    ),
                    {
                        "requester_user_id": _USER_ID,
                        "session_id": _SESSION_ID,
                    },
                )

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO action_executions (
                        id,
                        session_id,
                        input_buffer_id,
                        action_type,
                        action,
                        owner_generation,
                        status,
                        failure_summary
                    )
                    VALUES (
                        'action-execution-null-sender',
                        :session_id,
                        'input-buffer-null-sender',
                        'create_git_worktree',
                        '{
                            "type": "create_git_worktree",
                            "source_project_path": "/workspace/project",
                            "starting_ref": "main"
                        }'::jsonb,
                        0,
                        'pending',
                        NULL
                    )
                    """
                ),
                {"session_id": _SESSION_ID},
            )

        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        """
                    SELECT sender_user_id
                    FROM action_executions
                    WHERE id = 'action-execution-null-sender'
                    """
                    )
                )
                is None
            )

        with pytest.raises(RuntimeError, match="forward-only"):
            alembic_command.downgrade(config, _PARENT_REVISION)
    finally:
        migration_database.close()
