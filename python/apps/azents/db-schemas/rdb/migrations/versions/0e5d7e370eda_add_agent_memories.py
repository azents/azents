"""add_agent_memories

Revision ID: 0e5d7e370eda
Revises: 79556eb5d839
Create Date: 2026-04-26 16:00:00.000000

"""

# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0e5d7e370eda"
down_revision: str | Sequence[str] | None = "79556eb5d839"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the agent_memories table and memory_scope ENUM."""
    # Create the ENUM type before the table
    memory_scope_enum = postgresql.ENUM(
        "agent", "user", name="memory_scope", create_type=False
    )
    memory_scope_enum.create(op.get_bind(), checkfirst=True)

    # Create the agent_memories table
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(32), nullable=True),
        sa.Column(
            "scope",
            postgresql.ENUM("agent", "user", name="memory_scope", create_type=False),
            nullable=False,
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Partial unique indexes
    op.create_index(
        "uq_agent_memories_agent_scope",
        "agent_memories",
        ["agent_id", "name"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "uq_agent_memories_user_scope",
        "agent_memories",
        ["agent_id", "user_id", "name"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )

    # Regular partial indexes
    op.create_index(
        "ix_agent_memories_agent_id",
        "agent_memories",
        ["agent_id"],
        postgresql_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "ix_agent_memories_agent_user",
        "agent_memories",
        ["agent_id", "user_id"],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the agent_memories table and related ENUM type."""
    op.drop_index("ix_agent_memories_agent_user", table_name="agent_memories")
    op.drop_index("ix_agent_memories_agent_id", table_name="agent_memories")
    op.drop_index("uq_agent_memories_user_scope", table_name="agent_memories")
    op.drop_index("uq_agent_memories_agent_scope", table_name="agent_memories")

    op.drop_table("agent_memories")

    # Drop the ENUM type after dropping the table
    postgresql.ENUM(name="memory_scope").drop(op.get_bind(), checkfirst=True)
