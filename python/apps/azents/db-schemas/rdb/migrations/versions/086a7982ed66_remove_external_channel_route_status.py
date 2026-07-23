"""remove external channel route status

Revision ID: 086a7982ed66
Revises: ddbafb0f6ce0
Create Date: 2026-07-23 00:14:48.256652

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "086a7982ed66"
down_revision: str | Sequence[str] | None = "ddbafb0f6ce0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    duplicate_dedicated_connection = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT connection_id
            FROM external_channel_agent_routes
            WHERE route_mode = 'dedicated'
            GROUP BY connection_id
            HAVING count(*) > 1
            ORDER BY connection_id
            LIMIT 1
            """
            )
        )
        .scalar_one_or_none()
    )
    if duplicate_dedicated_connection is not None:
        raise RuntimeError(
            "Cannot remove route status while a dedicated connection has multiple "
            f"routes: {duplicate_dedicated_connection}."
        )
    op.drop_index(
        "uq_external_channel_agent_routes_active_dedicated_connection",
        table_name="external_channel_agent_routes",
    )
    op.drop_index(
        "ix_external_channel_agent_routes_agent_id_status",
        table_name="external_channel_agent_routes",
    )
    op.drop_column("external_channel_agent_routes", "deactivated_at")
    op.drop_column("external_channel_agent_routes", "status")
    op.create_index(
        "ix_external_channel_agent_routes_agent_id",
        "external_channel_agent_routes",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "uq_external_channel_agent_routes_dedicated_connection",
        "external_channel_agent_routes",
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text("route_mode = 'dedicated'"),
    )
    sa.Enum("active", "inactive", name="external_channel_route_status").drop(
        op.get_bind()
    )


def downgrade() -> None:
    """Downgrade schema."""
    sa.Enum("active", "inactive", name="external_channel_route_status").create(
        op.get_bind()
    )
    op.drop_index(
        "uq_external_channel_agent_routes_dedicated_connection",
        table_name="external_channel_agent_routes",
    )
    op.drop_index(
        "ix_external_channel_agent_routes_agent_id",
        table_name="external_channel_agent_routes",
    )
    op.add_column(
        "external_channel_agent_routes",
        sa.Column(
            "status",
            postgresql.ENUM(
                "active",
                "inactive",
                name="external_channel_route_status",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_agent_routes",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE external_channel_agent_routes
            SET status = 'inactive',
                deactivated_at = now()
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE external_channel_agent_routes AS route
            SET status = 'active',
                deactivated_at = NULL
            FROM external_channel_connections AS connection,
                 agents
            WHERE connection.id = route.connection_id
              AND agents.id = route.agent_id
              AND connection.status IN ('active', 'degraded')
              AND agents.lifecycle_status = 'active'
            """
        )
    )
    op.alter_column(
        "external_channel_agent_routes",
        "status",
        existing_type=postgresql.ENUM(
            "active",
            "inactive",
            name="external_channel_route_status",
            create_type=False,
        ),
        nullable=False,
        server_default="active",
    )
    op.create_index(
        "ix_external_channel_agent_routes_agent_id_status",
        "external_channel_agent_routes",
        ["agent_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_external_channel_agent_routes_active_dedicated_connection",
        "external_channel_agent_routes",
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND route_mode = 'dedicated'"),
    )
