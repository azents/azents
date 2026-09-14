"""Add Runtime Web session routes."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "eebc06bf6bf0"
down_revision: str | Sequence[str] | None = "102901c54450"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the inactive one-per-Runtime Owner-session route."""
    op.create_table(
        "runtime_web_session_routes",
        sa.Column("runtime_id", sa.String(length=32), nullable=False),
        sa.Column("desired_generation", sa.BigInteger(), nullable=False),
        sa.Column("runner_generation", sa.BigInteger(), nullable=False),
        sa.Column("owner_replica_id", sa.String(length=255), nullable=False),
        sa.Column("owner_boot_id", sa.String(length=128), nullable=False),
        sa.Column("owner_address", sa.String(length=255), nullable=False),
        sa.Column("session_lease_id", sa.String(length=32), nullable=False),
        sa.Column("lease_generation", sa.BigInteger(), nullable=False),
        sa.Column("join_nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("protocol_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("draining_at", sa.DateTime(timezone=True), nullable=True),
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
            "desired_generation >= 1 AND runner_generation >= 1 "
            "AND lease_generation >= 1",
            name="ck_runtime_web_session_routes_generations",
        ),
        sa.CheckConstraint(
            "lease_expires_at > created_at "
            "AND (draining_at IS NULL OR draining_at <= lease_expires_at)",
            name="ck_runtime_web_session_routes_deadlines",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_id"],
            ["agent_runtimes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("runtime_id"),
        sa.UniqueConstraint(
            "join_nonce_hash",
            name="uq_runtime_web_session_routes_join_nonce_hash",
        ),
        sa.UniqueConstraint(
            "session_lease_id",
            name="uq_runtime_web_session_routes_session_lease",
        ),
    )
    op.create_index(
        "ix_runtime_web_session_routes_generation",
        "runtime_web_session_routes",
        ["desired_generation", "runner_generation", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_web_session_routes_owner_lease",
        "runtime_web_session_routes",
        ["owner_boot_id", "lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the inactive Owner-session route."""
    op.drop_index(
        "ix_runtime_web_session_routes_owner_lease",
        table_name="runtime_web_session_routes",
    )
    op.drop_index(
        "ix_runtime_web_session_routes_generation",
        table_name="runtime_web_session_routes",
    )
    op.drop_table("runtime_web_session_routes")
