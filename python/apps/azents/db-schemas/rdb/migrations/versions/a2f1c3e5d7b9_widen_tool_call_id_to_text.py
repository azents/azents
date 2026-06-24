"""widen tool_call_id to text

Revision ID: a2f1c3e5d7b9
Revises: 95bc6cdc7b07
Create Date: 2026-03-04 14:40:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2f1c3e5d7b9"
down_revision: str | Sequence[str] | None = "95bc6cdc7b07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Change events.tool_call_id from VARCHAR(255) to TEXT."""
    op.alter_column(
        "events",
        "tool_call_id",
        type_=sa.Text,
        existing_type=sa.String(255),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Change events.tool_call_id back from TEXT to VARCHAR(255)."""
    op.alter_column(
        "events",
        "tool_call_id",
        type_=sa.String(255),
        existing_type=sa.Text,
        existing_nullable=True,
    )
