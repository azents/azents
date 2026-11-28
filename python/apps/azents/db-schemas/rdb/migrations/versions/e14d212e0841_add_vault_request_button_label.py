"""add vault request button label

Revision ID: e14d212e0841
Revises: 44439b9001d3
Create Date: 2026-11-28 00:26:08.860266

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e14d212e0841"
down_revision: str | Sequence[str] | None = "44439b9001d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_vault_requests", sa.Column("button_label", sa.String(75), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_vault_requests", "button_label")
