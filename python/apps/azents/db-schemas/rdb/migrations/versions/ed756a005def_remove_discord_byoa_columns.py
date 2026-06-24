"""remove discord byoa columns

Revision ID: ed756a005def
Revises: df34bef59381
Create Date: 2026-03-10 18:00:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ed756a005def"
down_revision: str | Sequence[str] | None = "df34bef59381"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("discord_installations", "agent_id")
    op.drop_column("discord_installations", "mode")
    sa.Enum("platform", "byoa", name="discord_installation_mode").drop(op.get_bind())


def downgrade() -> None:
    """Downgrade schema."""
    sa.Enum("platform", "byoa", name="discord_installation_mode").create(op.get_bind())
    op.add_column(
        "discord_installations",
        sa.Column(
            "mode",
            postgresql.ENUM(
                "platform",
                "byoa",
                name="discord_installation_mode",
                create_type=False,
            ),
            nullable=False,
            server_default="platform",
        ),
    )
    op.add_column(
        "discord_installations",
        sa.Column("agent_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "discord_installations_agent_id_fkey",
        "discord_installations",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
