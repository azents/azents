"""Scope pending context by Agent route."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "adbbafc73d6f"
down_revision: str | Sequence[str] | None = "e31030a18e98"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "external_channel_pending_contexts",
        sa.Column("route_id", sa.String(length=32), nullable=False),
    )
    op.create_foreign_key(
        "external_channel_pending_contexts_route_id_fkey",
        "external_channel_pending_contexts",
        "external_channel_agent_routes",
        ["route_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_index(
        "ix_external_channel_pending_ctx_resource_position",
        table_name="external_channel_pending_contexts",
    )
    op.create_index(
        "ix_external_channel_pending_ctx_route_resource_position",
        "external_channel_pending_contexts",
        ["route_id", "resource_id", "provider_position"],
        unique=False,
    )
    op.drop_constraint(
        "uq_external_channel_pending_contexts_resource_message_revision",
        "external_channel_pending_contexts",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_external_channel_pending_contexts_route_resource_message_revision",
        "external_channel_pending_contexts",
        ["route_id", "resource_id", "message_revision_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_external_channel_pending_contexts_route_resource_message_revision",
        "external_channel_pending_contexts",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_external_channel_pending_contexts_resource_message_revision",
        "external_channel_pending_contexts",
        ["resource_id", "message_revision_id"],
    )
    op.drop_index(
        "ix_external_channel_pending_ctx_route_resource_position",
        table_name="external_channel_pending_contexts",
    )
    op.create_index(
        "ix_external_channel_pending_ctx_resource_position",
        "external_channel_pending_contexts",
        ["resource_id", "provider_position"],
        unique=False,
    )
    op.drop_constraint(
        "external_channel_pending_contexts_route_id_fkey",
        "external_channel_pending_contexts",
        type_="foreignkey",
    )
    op.drop_column("external_channel_pending_contexts", "route_id")
