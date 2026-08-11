"""add Runtime add transition receipts

Revision ID: 114473afc4be
Revises: 8b9f418cf037
Create Date: 2026-08-10 14:24:12.820190

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "114473afc4be"
down_revision: str | Sequence[str] | None = "8b9f418cf037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_runtime_add_receipts",
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column(
            "workspace_runtime_profile_id",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "expected_capability_version",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "committed_capability_version",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "committed_runtime_profile_selection_version",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
        sa.Column(
            "runtime_configuration_revision_id",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "runtime_desired_generation",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "expected_capability_version >= 1 "
            "AND committed_capability_version = expected_capability_version + 1",
            name="ck_agent_runtime_add_receipts_capability_versions",
        ),
        sa.CheckConstraint(
            "committed_runtime_profile_selection_version >= 2",
            name="ck_agent_runtime_add_receipts_profile_version",
        ),
        sa.CheckConstraint(
            "runtime_desired_generation >= 0",
            name="ck_agent_runtime_add_receipts_runtime_generation",
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
            ["workspace_runtime_profile_id"],
            ["workspace_runtime_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"],
            ["agent_runtimes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_configuration_revision_id"],
            ["runtime_configuration_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_runtime_add_receipts_agent_created_at",
        "agent_runtime_add_receipts",
        ["agent_id", "created_at"],
    )
    op.create_index(
        "uq_agent_runtime_add_receipts_agent_idempotency",
        "agent_runtime_add_receipts",
        ["agent_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_agent_runtime_add_receipts_agent_idempotency",
        table_name="agent_runtime_add_receipts",
    )
    op.drop_index(
        "ix_agent_runtime_add_receipts_agent_created_at",
        table_name="agent_runtime_add_receipts",
    )
    op.drop_table("agent_runtime_add_receipts")
