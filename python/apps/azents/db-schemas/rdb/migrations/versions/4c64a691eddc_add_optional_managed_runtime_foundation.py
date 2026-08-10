"""Add optional managed Runtime persistence foundation.

Revision ID: 4c64a691eddc
Revises: 346454f625fe
Create Date: 2026-08-10 09:40:06.382193

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4c64a691eddc"
down_revision: str | Sequence[str] | None = "346454f625fe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    agent_runtime_capability = postgresql.ENUM(
        "none",
        "managed",
        "removing",
        name="agent_runtime_capability",
        create_type=False,
    )
    agent_runtime_removal_status = postgresql.ENUM(
        "pending",
        "running",
        "retry_wait",
        "completed",
        name="agent_runtime_removal_status",
        create_type=False,
    )
    agent_runtime_removal_stage = postgresql.ENUM(
        "fencing",
        "interrupting_work",
        "cleaning_product_state",
        "deleting_runtime",
        "finalizing",
        "completed",
        name="agent_runtime_removal_stage",
        create_type=False,
    )
    terminal_delete_acknowledgement_kind = postgresql.ENUM(
        "provider_report",
        "no_physical_binding",
        name="runtime_terminal_delete_acknowledgement_kind",
        create_type=False,
    )
    session_working_folder_binding_state = postgresql.ENUM(
        "none",
        "pending",
        "bound",
        "invalidated",
        name="session_working_folder_binding_state",
        create_type=False,
    )
    agent_runtime_capability.create(op.get_bind(), checkfirst=True)
    agent_runtime_removal_status.create(op.get_bind(), checkfirst=True)
    agent_runtime_removal_stage.create(op.get_bind(), checkfirst=True)
    terminal_delete_acknowledgement_kind.create(op.get_bind(), checkfirst=True)
    session_working_folder_binding_state.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "agents",
        sa.Column(
            "runtime_capability",
            agent_runtime_capability,
            nullable=False,
            server_default="managed",
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "runtime_capability_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_agents_runtime_capability_version_positive",
        "agents",
        "runtime_capability_version >= 1",
    )
    op.create_check_constraint(
        "ck_agents_runtime_capability_profile",
        "agents",
        "runtime_capability = 'managed' OR runtime_profile_id IS NULL",
    )

    op.add_column(
        "agent_runtimes",
        sa.Column(
            "terminal_delete_acknowledgement_kind",
            terminal_delete_acknowledgement_kind,
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE agent_runtimes "
        "SET terminal_delete_acknowledgement_kind = 'provider_report' "
        "WHERE terminal_delete_acknowledged_generation IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_agent_runtimes_terminal_delete_acknowledgement",
        "agent_runtimes",
        "(terminal_delete_acknowledged_generation IS NULL "
        "AND terminal_delete_acknowledged_at IS NULL "
        "AND terminal_delete_acknowledgement_kind IS NULL) OR "
        "(terminal_delete_acknowledged_generation IS NOT NULL "
        "AND terminal_delete_acknowledged_at IS NOT NULL "
        "AND terminal_delete_acknowledgement_kind IS NOT NULL)",
    )

    op.create_table(
        "agent_runtime_removal_operations",
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column(
            "requested_by_workspace_user_id",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("expected_capability_version", sa.BigInteger(), nullable=False),
        sa.Column("committed_capability_version", sa.BigInteger(), nullable=False),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("destructive_scope_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            agent_runtime_removal_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "stage",
            agent_runtime_removal_stage,
            nullable=False,
            server_default="fencing",
        ),
        sa.Column(
            "active_root_session_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "active_subagent_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "active_run_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "queued_runtime_action_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("cleanup_cursor_context_id", sa.String(length=32), nullable=True),
        sa.Column(
            "cleanup_scanned_context_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cleanup_invalidated_context_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "product_cleanup_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("physical_deletion_required", sa.Boolean(), nullable=True),
        sa.Column(
            "target_terminal_delete_generation",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "physical_delete_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "physical_delete_acknowledgement_kind",
            terminal_delete_acknowledgement_kind,
            nullable=True,
        ),
        sa.Column(
            "physical_delete_acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_kind", sa.String(length=120), nullable=True),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "expected_capability_version >= 1 "
            "AND committed_capability_version > expected_capability_version",
            name="ck_agent_runtime_removal_operations_capability_versions",
        ),
        sa.CheckConstraint(
            "destructive_scope_version >= 1",
            name="ck_agent_runtime_removal_operations_scope_version",
        ),
        sa.CheckConstraint(
            "active_root_session_count >= 0 "
            "AND active_subagent_count >= 0 "
            "AND active_run_count >= 0 "
            "AND queued_runtime_action_count >= 0 "
            "AND cleanup_scanned_context_count >= 0 "
            "AND cleanup_invalidated_context_count >= 0 "
            "AND cleanup_invalidated_context_count "
            "<= cleanup_scanned_context_count",
            name="ck_agent_runtime_removal_operations_nonnegative_counts",
        ),
        sa.CheckConstraint(
            "target_terminal_delete_generation IS NULL "
            "OR target_terminal_delete_generation >= 1",
            name="ck_agent_runtime_removal_operations_target_generation",
        ),
        sa.CheckConstraint(
            "(physical_delete_acknowledged_at IS NULL "
            "AND physical_delete_acknowledgement_kind IS NULL) OR "
            "(physical_delete_acknowledged_at IS NOT NULL "
            "AND physical_delete_acknowledgement_kind IS NOT NULL)",
            name="ck_agent_runtime_removal_operations_acknowledgement",
        ),
        sa.CheckConstraint(
            "(physical_deletion_required IS NULL "
            "AND target_terminal_delete_generation IS NULL "
            "AND physical_delete_requested_at IS NULL "
            "AND physical_delete_acknowledged_at IS NULL) OR "
            "(physical_deletion_required = false "
            "AND target_terminal_delete_generation IS NULL "
            "AND physical_delete_requested_at IS NULL "
            "AND physical_delete_acknowledged_at IS NULL) OR "
            "(physical_deletion_required = true "
            "AND target_terminal_delete_generation IS NOT NULL "
            "AND physical_delete_requested_at IS NOT NULL)",
            name="ck_agent_runtime_removal_operations_physical_target",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND stage = 'completed' "
            "AND completed_at IS NOT NULL "
            "AND product_cleanup_completed_at IS NOT NULL "
            "AND physical_deletion_required IS NOT NULL "
            "AND (physical_deletion_required = false OR "
            "physical_delete_acknowledged_at IS NOT NULL)) OR "
            "(status != 'completed' AND stage != 'completed' "
            "AND completed_at IS NULL)",
            name="ck_agent_runtime_removal_operations_completion",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"],
            ["agent_runtimes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_runtime_removal_operations_agent_created_at",
        "agent_runtime_removal_operations",
        ["agent_id", "created_at"],
    )
    op.create_index(
        "ix_agent_runtime_removal_operations_status_next_attempt_at",
        "agent_runtime_removal_operations",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "uq_agent_runtime_removal_operations_active_agent",
        "agent_runtime_removal_operations",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("status != 'completed'"),
    )
    op.create_index(
        "uq_agent_runtime_removal_operations_agent_idempotency",
        "agent_runtime_removal_operations",
        ["agent_id", "idempotency_key"],
        unique=True,
    )

    op.add_column(
        "session_agent_contexts",
        sa.Column(
            "working_folder_binding_state",
            session_working_folder_binding_state,
            nullable=False,
            server_default="bound",
        ),
    )
    op.add_column(
        "session_agent_contexts",
        sa.Column(
            "working_folder_invalidated_by_removal_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "session_agent_contexts",
        sa.Column(
            "working_folder_invalidated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.alter_column(
        "session_agent_contexts",
        "working_folder_path",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_session_contexts_invalidated_removal_id",
        "session_agent_contexts",
        "agent_runtime_removal_operations",
        ["working_folder_invalidated_by_removal_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_check_constraint(
        "ck_session_agent_contexts_working_folder_binding",
        "session_agent_contexts",
        "(working_folder_binding_state = 'none' "
        "AND working_folder_path IS NULL "
        "AND agent_runtime_id IS NULL "
        "AND working_folder_invalidated_by_removal_id IS NULL "
        "AND working_folder_invalidated_at IS NULL) OR "
        "(working_folder_binding_state = 'pending' "
        "AND working_folder_path IS NULL "
        "AND agent_runtime_id IS NOT NULL "
        "AND working_folder_invalidated_by_removal_id IS NULL "
        "AND working_folder_invalidated_at IS NULL) OR "
        "(working_folder_binding_state = 'bound' "
        "AND working_folder_path IS NOT NULL "
        "AND agent_runtime_id IS NOT NULL "
        "AND working_folder_invalidated_by_removal_id IS NULL "
        "AND working_folder_invalidated_at IS NULL) OR "
        "(working_folder_binding_state = 'invalidated' "
        "AND agent_runtime_id IS NOT NULL "
        "AND working_folder_invalidated_by_removal_id IS NOT NULL "
        "AND working_folder_invalidated_at IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_session_agent_contexts_working_folder_binding",
        "session_agent_contexts",
        type_="check",
    )
    op.drop_constraint(
        "fk_session_contexts_invalidated_removal_id",
        "session_agent_contexts",
        type_="foreignkey",
    )
    op.alter_column(
        "session_agent_contexts",
        "working_folder_path",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.drop_column("session_agent_contexts", "working_folder_invalidated_at")
    op.drop_column(
        "session_agent_contexts",
        "working_folder_invalidated_by_removal_id",
    )
    op.drop_column("session_agent_contexts", "working_folder_binding_state")

    op.drop_index(
        "uq_agent_runtime_removal_operations_agent_idempotency",
        table_name="agent_runtime_removal_operations",
    )
    op.drop_index(
        "uq_agent_runtime_removal_operations_active_agent",
        table_name="agent_runtime_removal_operations",
        postgresql_where=sa.text("status != 'completed'"),
    )
    op.drop_index(
        "ix_agent_runtime_removal_operations_status_next_attempt_at",
        table_name="agent_runtime_removal_operations",
    )
    op.drop_index(
        "ix_agent_runtime_removal_operations_agent_created_at",
        table_name="agent_runtime_removal_operations",
    )
    op.drop_table("agent_runtime_removal_operations")

    op.drop_constraint(
        "ck_agent_runtimes_terminal_delete_acknowledgement",
        "agent_runtimes",
        type_="check",
    )
    op.drop_column("agent_runtimes", "terminal_delete_acknowledgement_kind")

    op.drop_constraint(
        "ck_agents_runtime_capability_profile",
        "agents",
        type_="check",
    )
    op.drop_constraint(
        "ck_agents_runtime_capability_version_positive",
        "agents",
        type_="check",
    )
    op.drop_column("agents", "runtime_capability_version")
    op.drop_column("agents", "runtime_capability")

    postgresql.ENUM(name="session_working_folder_binding_state").drop(
        op.get_bind(),
        checkfirst=True,
    )
    postgresql.ENUM(name="runtime_terminal_delete_acknowledgement_kind").drop(
        op.get_bind(),
        checkfirst=True,
    )
    postgresql.ENUM(name="agent_runtime_removal_stage").drop(
        op.get_bind(),
        checkfirst=True,
    )
    postgresql.ENUM(name="agent_runtime_removal_status").drop(
        op.get_bind(),
        checkfirst=True,
    )
    postgresql.ENUM(name="agent_runtime_capability").drop(
        op.get_bind(),
        checkfirst=True,
    )
