"""add_subagent_session_type

Revision ID: ddf5e52ff2d8
Revises: 8c5ae715eef4
Create Date: 2026-03-06 07:22:01.850647

"""

# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ddf5e52ff2d8"
down_revision: str | Sequence[str] | None = "8c5ae715eef4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the 'subagent' value to the conversation_session_type ENUM."""
    op.execute(
        "ALTER TYPE conversation_session_type ADD VALUE IF NOT EXISTS 'subagent'"
    )


def downgrade() -> None:
    """Pass because deleting ENUM values is not supported in PostgreSQL."""
    pass
