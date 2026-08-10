"""add external channel ingress queue

Revision ID: b53dacd10814
Revises: a9d8b3e5803c
Create Date: 2026-08-10 09:43:27.609419

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b53dacd10814"
down_revision: str | Sequence[str] | None = "a9d8b3e5803c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add active Session-bound ingress queue state."""
    authority_kind = postgresql.ENUM(
        "configuration",
        "lease",
        "durable_replay",
        name="external_channel_ingress_authority_kind",
    )
    item_state = postgresql.ENUM(
        "pending",
        "processing",
        "retry_waiting",
        name="external_channel_ingress_item_state",
    )
    authority_kind.create(op.get_bind(), checkfirst=False)
    item_state.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "external_channel_ingress_sessions",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "first_batch_pending",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("current_batch_id", sa.String(length=32), nullable=True),
        sa.Column(
            "current_batch_started_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(current_batch_id IS NULL AND current_batch_started_at IS NULL) OR "
            "(current_batch_id IS NOT NULL AND current_batch_started_at IS NOT NULL "
            "AND lease_owner IS NOT NULL)",
            name="ck_external_channel_ingress_sessions_batch",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL AND lease_acquired_at IS NULL "
            "AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_acquired_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL)",
            name="ck_external_channel_ingress_sessions_lease",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        "ix_external_channel_ingress_sessions_recovery",
        "external_channel_ingress_sessions",
        ["lease_expires_at", "updated_at"],
        unique=False,
    )

    op.create_table(
        "external_channel_ingress_items",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("queue_key", sa.String(length=32), nullable=False),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(name="external_channel_provider", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "ingress_profile",
            postgresql.ENUM(name="external_channel_ingress_profile", create_type=False),
            nullable=False,
        ),
        sa.Column("configuration_generation", sa.Integer(), nullable=False),
        sa.Column(
            "authority_kind",
            postgresql.ENUM(
                name="external_channel_ingress_authority_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("authority_lease_owner", sa.String(length=255), nullable=True),
        sa.Column("authority_lease_generation", sa.Integer(), nullable=True),
        sa.Column("provider_event_type", sa.String(length=120), nullable=False),
        sa.Column("provider_tenant_id", sa.String(length=255), nullable=False),
        sa.Column(
            "scope_kind",
            postgresql.ENUM(
                name="external_channel_conversation_scope_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("provider_channel_id", sa.Text(), nullable=False),
        sa.Column("provider_parent_channel_id", sa.Text(), nullable=True),
        sa.Column("provider_thread_key", sa.Text(), nullable=True),
        sa.Column("delivery_thread_key", sa.Text(), nullable=True),
        sa.Column("provider_resource_key", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.String(length=32), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column("conversation_position_id", sa.String(length=32), nullable=False),
        sa.Column("principal_id", sa.String(length=32), nullable=False),
        sa.Column("trigger_provider_message_key", sa.Text(), nullable=False),
        sa.Column("trigger_provider_message_id", sa.Text(), nullable=False),
        sa.Column("trigger_position", sa.Text(), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=True),
        sa.Column("invocation", sa.Boolean(), nullable=False),
        sa.Column("invocation_id", sa.String(length=255), nullable=False),
        sa.Column("initial_title_eligible", sa.Boolean(), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(
                name="external_channel_ingress_item_state",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_owner", sa.String(length=255), nullable=True),
        sa.Column("processing_generation", sa.Integer(), nullable=True),
        sa.Column("batch_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(state = 'pending' AND next_attempt_at IS NULL "
            "AND processing_owner IS NULL AND processing_generation IS NULL "
            "AND batch_id IS NULL) OR "
            "(state = 'retry_waiting' AND next_attempt_at IS NOT NULL "
            "AND processing_owner IS NULL AND processing_generation IS NULL "
            "AND batch_id IS NULL) OR "
            "(state = 'processing' AND next_attempt_at IS NULL "
            "AND processing_owner IS NOT NULL AND processing_generation IS NOT NULL "
            "AND batch_id IS NOT NULL)",
            name="ck_external_channel_ingress_items_active_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 5",
            name="ck_external_channel_ingress_items_attempt_count",
        ),
        sa.CheckConstraint(
            "(authority_kind = 'lease' AND authority_lease_owner IS NOT NULL) OR "
            "(authority_kind <> 'lease' AND authority_lease_owner IS NULL "
            "AND authority_lease_generation IS NULL)",
            name="ck_external_channel_ingress_items_authority",
        ),
        sa.CheckConstraint(
            "(scope_kind = 'parent_channel' AND provider_thread_key IS NULL) OR "
            "(scope_kind = 'thread' AND provider_thread_key IS NOT NULL)",
            name="ck_external_channel_ingress_items_scope_key",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["external_channel_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["external_channel_connections.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_position_id"],
            ["external_channel_conversation_positions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["external_channel_principals.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["external_channel_resources.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["external_channel_ingress_sessions.session_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "deduplication_key",
            name="uq_external_channel_ingress_items_active_identity",
        ),
        sa.UniqueConstraint(
            "queue_key",
            name="uq_external_channel_ingress_items_queue_key",
        ),
    )
    op.create_index(
        "ix_external_channel_ingress_items_position",
        "external_channel_ingress_items",
        ["conversation_position_id", "trigger_position"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_ingress_items_session_due_queue",
        "external_channel_ingress_items",
        ["session_id", "state", "next_attempt_at", "queue_key"],
        unique=False,
    )


def downgrade() -> None:
    """Remove active Session-bound ingress queue state."""
    op.drop_index(
        "ix_external_channel_ingress_items_session_due_queue",
        table_name="external_channel_ingress_items",
    )
    op.drop_index(
        "ix_external_channel_ingress_items_position",
        table_name="external_channel_ingress_items",
    )
    op.drop_table("external_channel_ingress_items")
    op.drop_index(
        "ix_external_channel_ingress_sessions_recovery",
        table_name="external_channel_ingress_sessions",
    )
    op.drop_table("external_channel_ingress_sessions")
    postgresql.ENUM(name="external_channel_ingress_item_state").drop(
        op.get_bind(),
        checkfirst=False,
    )
    postgresql.ENUM(name="external_channel_ingress_authority_kind").drop(
        op.get_bind(),
        checkfirst=False,
    )
