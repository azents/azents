"""add agent project defaults

Revision ID: 0d2a6cf4b7a1
Revises: fe0e32010308
Create Date: 2026-06-29 16:35:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0d2a6cf4b7a1"
down_revision: str | Sequence[str] | None = "fe0e32010308"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_project_defaults",
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "path",
            name="uq_agent_project_defaults_agent_path",
        ),
        sa.UniqueConstraint(
            "agent_id",
            "position",
            name="uq_agent_project_defaults_agent_position",
        ),
    )
    op.create_index(
        "ix_agent_project_defaults_agent_position",
        "agent_project_defaults",
        ["agent_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_agent_project_defaults_agent_position",
        table_name="agent_project_defaults",
    )
    op.drop_table("agent_project_defaults")
