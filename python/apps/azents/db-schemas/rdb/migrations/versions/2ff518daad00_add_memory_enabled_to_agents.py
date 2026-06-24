"""add_memory_enabled_to_agents

Revision ID: 2ff518daad00
Revises: 9e78ce79930f
Create Date: 2026-03-22 16:30:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2ff518daad00"
down_revision: str = "9e78ce79930f"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "memory_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "memory_enabled")
