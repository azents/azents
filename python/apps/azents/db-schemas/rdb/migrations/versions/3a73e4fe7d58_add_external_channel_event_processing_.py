"""add external channel event processing state

Revision ID: 3a73e4fe7d58
Revises: e210c94fad48
Create Date: 2026-07-22 01:47:00.708727

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3a73e4fe7d58"
down_revision: str | Sequence[str] | None = "e210c94fad48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    hydration_status = postgresql.ENUM(
        "pending",
        "running",
        "complete",
        "bounded",
        "incomplete",
        name="external_channel_hydration_status",
    )
    binding_activation_status = postgresql.ENUM(
        "waiting_hydration",
        "active",
        name="external_channel_binding_activation_status",
    )
    hydration_status.create(bind, checkfirst=True)
    binding_activation_status.create(bind, checkfirst=True)
    op.execute(
        "ALTER TYPE agent_session_start_reason "
        "ADD VALUE IF NOT EXISTS 'external_channel'"
    )
    op.add_column(
        "external_channel_resources",
        sa.Column(
            "hydration_status",
            hydration_status,
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column("hydration_cursor", sa.Text(), nullable=True),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column(
            "hydration_high_watermark_position",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column(
            "reconciliation_boundary_received_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column(
            "reconciliation_boundary_event_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column(
            "hydration_error_kind",
            sa.String(length=120),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column("hydration_error_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column(
            "hydration_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column(
            "hydration_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_external_channel_events_connection_correlation_status",
        "external_channel_events",
        ["connection_id", "resource_correlation_key", "status", "received_at"],
        unique=False,
    )
    op.add_column(
        "external_channel_bindings",
        sa.Column(
            "activation_status",
            binding_activation_status,
            server_default="waiting_hydration",
            nullable=False,
        ),
    )
    op.add_column(
        "external_channel_bindings",
        sa.Column(
            "activation_trigger_message_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_bindings",
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_external_channel_bindings_activation_trigger_message",
        "external_channel_bindings",
        "external_channel_messages",
        ["activation_trigger_message_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_external_channel_bindings_activation_trigger_message",
        "external_channel_bindings",
        type_="foreignkey",
    )
    op.drop_column("external_channel_bindings", "activated_at")
    op.drop_column(
        "external_channel_bindings",
        "activation_trigger_message_id",
    )
    op.drop_column("external_channel_bindings", "activation_status")
    op.drop_index(
        "ix_external_channel_events_connection_correlation_status",
        table_name="external_channel_events",
    )
    op.drop_column("external_channel_resources", "hydration_completed_at")
    op.drop_column("external_channel_resources", "hydration_started_at")
    op.drop_column("external_channel_resources", "hydration_error_summary")
    op.drop_column("external_channel_resources", "hydration_error_kind")
    op.drop_column(
        "external_channel_resources",
        "reconciliation_boundary_event_id",
    )
    op.drop_column(
        "external_channel_resources",
        "reconciliation_boundary_received_at",
    )
    op.drop_column(
        "external_channel_resources",
        "hydration_high_watermark_position",
    )
    op.drop_column("external_channel_resources", "hydration_cursor")
    op.drop_column("external_channel_resources", "hydration_status")
    bind = op.get_bind()
    postgresql.ENUM(
        name="external_channel_binding_activation_status",
    ).drop(bind, checkfirst=True)
    postgresql.ENUM(
        name="external_channel_hydration_status",
    ).drop(bind, checkfirst=True)
