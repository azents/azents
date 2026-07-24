"""add agent automatic project policy

Revision ID: 995d915ed6d6
Revises: b976b12168b5
Create Date: 2026-07-24 10:06:10.096409

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "995d915ed6d6"
down_revision: str | Sequence[str] | None = "b976b12168b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_automatic_project_settings",
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column(
            "revision",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("updated_by_workspace_user_id", sa.String(length=32), nullable=True),
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
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_agent_automatic_project_settings_revision_positive",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["updated_by_workspace_user_id"],
            ["workspace_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("agent_id"),
    )
    op.create_table(
        "agent_automatic_project_items",
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
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_automatic_project_settings.agent_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "path",
            name="uq_agent_automatic_project_items_agent_path",
        ),
        sa.UniqueConstraint(
            "agent_id",
            "position",
            name="uq_agent_automatic_project_items_agent_position",
        ),
    )
    op.create_index(
        "ix_agent_automatic_project_items_agent_position",
        "agent_automatic_project_items",
        ["agent_id", "position"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO agent_automatic_project_settings (
                agent_id,
                revision,
                updated_by_workspace_user_id,
                created_at,
                updated_at
            )
            SELECT
                agents.id,
                1,
                NULL,
                agents.created_at,
                agents.updated_at
            FROM agents
            """
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_agent_automatic_project_items_agent_position",
        table_name="agent_automatic_project_items",
    )
    op.drop_table("agent_automatic_project_items")
    op.drop_table("agent_automatic_project_settings")
