"""add provider generation to agent runtimes

Revision ID: 9274b83c64d5
Revises: f79809732650
Create Date: 2026-07-09 05:09:21.164523

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9274b83c64d5"
down_revision: str | Sequence[str] | None = "f79809732650"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "provider_generation",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_runtimes", "provider_generation")
