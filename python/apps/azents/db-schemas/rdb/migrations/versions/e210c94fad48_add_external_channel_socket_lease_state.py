"""add external channel socket lease state

Revision ID: e210c94fad48
Revises: adbbafc73d6f
Create Date: 2026-07-22 01:13:01.928305

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e210c94fad48"
down_revision: str | Sequence[str] | None = "adbbafc73d6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "external_channel_connections",
        sa.Column("socket_lease_owner", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "external_channel_connections",
        sa.Column("socket_lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "external_channel_connections",
        sa.Column("socket_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "external_channel_connections",
        sa.Column(
            "socket_gap_detected_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_connections",
        sa.Column("socket_gap_reason", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_external_channel_connections_socket_lease_until",
        "external_channel_connections",
        ["socket_lease_until"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_external_channel_connections_socket_lease_until",
        table_name="external_channel_connections",
    )
    op.drop_column("external_channel_connections", "socket_gap_reason")
    op.drop_column("external_channel_connections", "socket_gap_detected_at")
    op.drop_column("external_channel_connections", "socket_heartbeat_at")
    op.drop_column("external_channel_connections", "socket_lease_until")
    op.drop_column("external_channel_connections", "socket_lease_owner")
