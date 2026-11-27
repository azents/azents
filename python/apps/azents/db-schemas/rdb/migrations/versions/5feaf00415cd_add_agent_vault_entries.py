"""add agent vault entries

Revision ID: 5feaf00415cd
Revises: aed428366a0a
Create Date: 2026-11-27 18:36:27.959747

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5feaf00415cd"
down_revision: str | Sequence[str] | None = "aed428366a0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_vault_entries",
        sa.Column("agent_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255, collation="C"), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("contributor_label", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "name"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("agent_vault_entries")
