"""Add Runtime Web transport leases."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "517e2d4e4fbf"
down_revision: str | Sequence[str] | None = "342b7778012c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "runtime_web_tunnel_routes",
        sa.Column("tunnel_id", sa.String(length=128), nullable=False),
        sa.Column("endpoint_id", sa.String(length=32), nullable=False),
        sa.Column("cycle_id", sa.String(length=32), nullable=False),
        sa.Column("endpoint_authority_revision", sa.BigInteger(), nullable=False),
        sa.Column("close_barrier", sa.BigInteger(), nullable=False),
        sa.Column("runtime_id", sa.String(length=32), nullable=False),
        sa.Column("desired_generation", sa.BigInteger(), nullable=False),
        sa.Column("runner_generation", sa.BigInteger(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("join_nonce", sa.String(length=128), nullable=False),
        sa.Column("owner_replica_id", sa.String(length=255), nullable=False),
        sa.Column("owner_boot_id", sa.String(length=128), nullable=False),
        sa.Column("owner_address", sa.String(length=255), nullable=False),
        sa.Column("route_lease_id", sa.String(length=32), nullable=False),
        sa.Column("lease_generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "registration_deadline_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "approval_deadline_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "transport_deadline_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
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
        sa.Column(
            "updated_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "registration_deadline_at <= transport_deadline_at "
            "AND approval_deadline_at <= transport_deadline_at "
            "AND lease_expires_at <= transport_deadline_at",
            name="ck_runtime_web_tunnel_routes_deadlines",
        ),
        sa.CheckConstraint(
            "desired_generation >= 1 AND runner_generation >= 1",
            name="ck_runtime_web_tunnel_routes_generations",
        ),
        sa.CheckConstraint(
            "port >= 1 AND port <= 65535",
            name="ck_runtime_web_tunnel_routes_port",
        ),
        sa.CheckConstraint(
            "endpoint_authority_revision >= 0 AND close_barrier >= 0 "
            "AND lease_generation >= 1",
            name="ck_runtime_web_tunnel_routes_revisions",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["runtime_web_cycles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["runtime_web_endpoints.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_id"],
            ["agent_runtimes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tunnel_id"),
        sa.UniqueConstraint(
            "join_nonce",
            name="uq_runtime_web_tunnel_routes_join_nonce",
        ),
        sa.UniqueConstraint(
            "route_lease_id",
            name="uq_runtime_web_tunnel_routes_route_lease",
        ),
    )
    op.create_index(
        "ix_runtime_web_tunnel_routes_owner_lease",
        "runtime_web_tunnel_routes",
        ["owner_boot_id", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_web_tunnel_routes_runtime_generation",
        "runtime_web_tunnel_routes",
        ["runtime_id", "runner_generation", "lease_expires_at"],
        unique=False,
    )
    op.create_table(
        "runtime_web_admission_leases",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tunnel_id", sa.String(length=128), nullable=False),
        sa.Column("owner_boot_id", sa.String(length=128), nullable=False),
        sa.Column("lease_generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "lease_expires_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "reserved_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "lease_generation >= 1 AND reserved_bytes >= 0 "
            "AND lease_expires_at > created_at",
            name="ck_runtime_web_admission_leases_lease",
        ),
        sa.ForeignKeyConstraint(
            ["tunnel_id"],
            ["runtime_web_tunnel_routes.tunnel_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tunnel_id",
            name="uq_runtime_web_admission_leases_tunnel",
        ),
    )
    op.create_index(
        "ix_runtime_web_admission_leases_expiry",
        "runtime_web_admission_leases",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_web_admission_leases_owner",
        "runtime_web_admission_leases",
        ["owner_boot_id", "lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_runtime_web_admission_leases_owner",
        table_name="runtime_web_admission_leases",
    )
    op.drop_index(
        "ix_runtime_web_admission_leases_expiry",
        table_name="runtime_web_admission_leases",
    )
    op.drop_table("runtime_web_admission_leases")
    op.drop_index(
        "ix_runtime_web_tunnel_routes_runtime_generation",
        table_name="runtime_web_tunnel_routes",
    )
    op.drop_index(
        "ix_runtime_web_tunnel_routes_owner_lease",
        table_name="runtime_web_tunnel_routes",
    )
    op.drop_table("runtime_web_tunnel_routes")
