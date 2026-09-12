"""Add Runtime Web Gateway admission leases."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "a779d057128b"
down_revision: str | Sequence[str] | None = "07f7858f8d36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "runtime_web_gateway_admission_leases",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tunnel_id", sa.String(length=128), nullable=False),
        sa.Column("endpoint_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("websocket", sa.Boolean(), nullable=False),
        sa.Column(
            "lease_expires_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "lease_expires_at > created_at",
            name="ck_runtime_web_gateway_admission_leases_deadline",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["runtime_web_endpoints.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tunnel_id",
            name="uq_runtime_web_gateway_admission_leases_tunnel",
        ),
    )
    op.create_index(
        "ix_runtime_web_gateway_admission_leases_agent",
        "runtime_web_gateway_admission_leases",
        ["agent_id", "websocket", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_web_gateway_admission_leases_endpoint",
        "runtime_web_gateway_admission_leases",
        ["endpoint_id", "websocket", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_web_gateway_admission_leases_user",
        "runtime_web_gateway_admission_leases",
        ["user_id", "websocket", "lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_runtime_web_gateway_admission_leases_user",
        table_name="runtime_web_gateway_admission_leases",
    )
    op.drop_index(
        "ix_runtime_web_gateway_admission_leases_endpoint",
        table_name="runtime_web_gateway_admission_leases",
    )
    op.drop_index(
        "ix_runtime_web_gateway_admission_leases_agent",
        table_name="runtime_web_gateway_admission_leases",
    )
    op.drop_table("runtime_web_gateway_admission_leases")
