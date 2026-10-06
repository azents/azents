"""Extract common execution Sessions and single-writer Conversation profiles."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6a05f4a01f6f"
down_revision: str | Sequence[str] | None = "a332f5e0f329"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_sessions",
        sa.Column("lifecycle_root_session_id", sa.String(32), nullable=True),
    )
    op.create_foreign_key(
        "fk_session_lifecycle_root",
        "agent_sessions",
        "agent_sessions",
        ["lifecycle_root_session_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_agent_sessions_lifecycle_root_session_id",
        "agent_sessions",
        ["lifecycle_root_session_id"],
        postgresql_where=sa.text("lifecycle_root_session_id IS NOT NULL"),
    )
    op.create_unique_constraint(
        "uq_session_lifecycle_identity", "agent_sessions", ["id", "agent_id", "status"]
    )
    op.execute(
        """
        CREATE TABLE conversations (
                session_id VARCHAR(32) NOT NULL,
                agent_id VARCHAR(32) NOT NULL,
                session_status agent_session_status NOT NULL,
                handle VARCHAR(120) NOT NULL,
                session_kind agent_session_kind NOT NULL,
                primary_kind agent_session_primary_kind,
                product_mode agent_session_product_mode,
                associated_user_id VARCHAR(32),
                title VARCHAR(200),
                title_source agent_session_title_source,
                title_generated_at TIMESTAMP WITH TIME ZONE,
                title_generation_event_id VARCHAR(32),
                primary_model_reservation JSONB,
                primary_model_reservation_generation BIGINT DEFAULT 0 NOT NULL,
                title_model_operation_state JSONB,
                last_user_input_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
                pinned BOOLEAN DEFAULT false NOT NULL,
                pending_idle_continuation_run_id VARCHAR(32),
                pending_command_id VARCHAR(32),
                pending_command_name VARCHAR(120),
                pending_command_payload JSONB,
                pending_command_requester_user_id VARCHAR(32),
                pending_command_created_at TIMESTAMP WITH TIME ZONE,
                PRIMARY KEY (session_id),
                CONSTRAINT fk_conversation_session_lifecycle FOREIGN KEY(session_id,
        agent_id, session_status) REFERENCES agent_sessions (id, agent_id, status)
        ON DELETE CASCADE ON UPDATE CASCADE,
                CONSTRAINT ck_conversations_product_mode_ownership CHECK
        ((session_kind = 'root' AND product_mode IS NOT NULL AND ((product_mode =
        'team' AND associated_user_id IS NULL) OR (product_mode = 'user' AND
        associated_user_id IS NOT NULL AND primary_kind IS NULL))) OR (session_kind
        = 'subagent' AND product_mode IS NULL AND associated_user_id IS NULL AND
        primary_kind IS NULL)),
                CONSTRAINT uq_conversations_handle UNIQUE (handle),
                FOREIGN KEY(associated_user_id) REFERENCES users (id) ON DELETE
        RESTRICT,
                FOREIGN KEY(pending_idle_continuation_run_id) REFERENCES agent_runs
        (id) ON DELETE SET NULL,
                FOREIGN KEY(pending_command_requester_user_id) REFERENCES users (id)
        ON DELETE SET NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE session_execution_files (
                session_id VARCHAR(32) NOT NULL,
                path VARCHAR(512) NOT NULL,
                content TEXT NOT NULL,
                writable BOOLEAN NOT NULL,
                PRIMARY KEY (session_id, path),
                CONSTRAINT fk_session_execution_files_session FOREIGN
        KEY(session_id) REFERENCES agent_sessions (id) ON DELETE CASCADE,
                CONSTRAINT ck_session_execution_files_path CHECK (length(path) > 0)
        )
        """
    )
    op.execute(
        """
        INSERT INTO conversations (session_id, agent_id, session_status, handle,
        session_kind, primary_kind, product_mode, associated_user_id, title,
        title_source, title_generated_at, title_generation_event_id,
        primary_model_reservation, primary_model_reservation_generation,
        title_model_operation_state, last_user_input_at, pinned,
        pending_idle_continuation_run_id, pending_command_id, pending_command_name,
        pending_command_payload, pending_command_requester_user_id,
        pending_command_created_at) SELECT id, agent_id, status, handle,
        session_kind, primary_kind, product_mode, associated_user_id, title,
        title_source, title_generated_at, title_generation_event_id,
        primary_model_reservation, primary_model_reservation_generation,
        title_model_operation_state, last_user_input_at, pinned,
        pending_idle_continuation_run_id, pending_command_id, pending_command_name,
        pending_command_payload, pending_command_requester_user_id,
        pending_command_created_at FROM agent_sessions
        """
    )
    op.execute("""
        UPDATE agent_sessions AS execution
                SET lifecycle_root_session_id = root.agent_session_id
                FROM session_agents AS child
                JOIN session_agents AS root ON root.id = child.root_session_agent_id
                WHERE child.agent_session_id = execution.id
                  AND root.agent_session_id <> execution.id
        """)
    op.drop_constraint(
        "ck_agent_sessions_product_mode_ownership", "agent_sessions", type_="check"
    )
    op.drop_constraint("uq_agent_sessions_handle", "agent_sessions", type_="unique")
    op.drop_index("ix_agent_sessions_session_kind", table_name="agent_sessions")
    op.drop_index(
        "ix_agent_sessions_agent_active_last_user_input", table_name="agent_sessions"
    )
    op.drop_index("ix_agent_sessions_pending_command", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_active_auto_archive", table_name="agent_sessions")
    op.drop_index(
        "uq_agent_sessions_agent_active_team_primary", table_name="agent_sessions"
    )
    op.drop_index(
        "ix_agent_sessions_agent_associated_user_status", table_name="agent_sessions"
    )
    op.drop_index("ix_agent_sessions_associated_user_id", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_archived_purge_after", table_name="agent_sessions")
    op.drop_column("agent_sessions", "handle")
    op.drop_column("agent_sessions", "session_kind")
    op.drop_column("agent_sessions", "primary_kind")
    op.drop_column("agent_sessions", "product_mode")
    op.drop_column("agent_sessions", "associated_user_id")
    op.drop_column("agent_sessions", "title")
    op.drop_column("agent_sessions", "title_source")
    op.drop_column("agent_sessions", "title_generated_at")
    op.drop_column("agent_sessions", "title_generation_event_id")
    op.drop_column("agent_sessions", "primary_model_reservation")
    op.drop_column("agent_sessions", "primary_model_reservation_generation")
    op.drop_column("agent_sessions", "title_model_operation_state")
    op.drop_column("agent_sessions", "last_user_input_at")
    op.drop_column("agent_sessions", "pinned")
    op.drop_column("agent_sessions", "pending_idle_continuation_run_id")
    op.drop_column("agent_sessions", "pending_command_id")
    op.drop_column("agent_sessions", "pending_command_name")
    op.drop_column("agent_sessions", "pending_command_payload")
    op.drop_column("agent_sessions", "pending_command_requester_user_id")
    op.drop_column("agent_sessions", "pending_command_created_at")
    op.create_index(
        "ix_agent_sessions_archived_purge_after",
        "agent_sessions",
        ["purge_after"],
        postgresql_where=sa.text(
            "status = 'archived' AND lifecycle_root_session_id IS NULL "
            "AND purge_after IS NOT NULL"
        ),
    )
    op.execute(
        """
        CREATE INDEX ix_conversations_active_auto_archive ON conversations
        (session_id) WHERE session_status = 'active' AND session_kind = 'root' AND
        pinned = false
        """
    )
    op.execute(
        """
        CREATE INDEX ix_conversations_agent_active_last_user_input ON conversations
        (agent_id, primary_kind, last_user_input_at) WHERE session_status = 'active'
        """
    )
    op.execute(
        """
        CREATE INDEX ix_conversations_agent_associated_user_status ON conversations
        (agent_id, associated_user_id, session_status)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_conversations_associated_user_id ON conversations
        (associated_user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_conversations_pending_command ON conversations
        (pending_command_created_at) WHERE pending_command_id IS NOT NULL
        """
    )
    op.execute(
        "CREATE INDEX ix_conversations_session_kind ON conversations (session_kind)"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_conversations_agent_active_team_primary ON
        conversations (agent_id) WHERE session_status = 'active' AND primary_kind =
        'team_primary' AND product_mode = 'team'
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "irreversible: the common execution foundation can contain Sessions without "
        "Conversation profiles; old public Session storage cannot represent them"
    )
