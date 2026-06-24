"""add runtime lifecycle dispatch generation

Revision ID: 1524a89eb0e2
Revises: 137b8bd8c9d5
Create Date: 2026-05-25 15:02:23.678833

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1524a89eb0e2"
down_revision: str | Sequence[str] | None = "137b8bd8c9d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "last_lifecycle_dispatch_generation",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_runtimes_lifecycle_dispatch",
        "agent_runtimes",
        ["desired_generation", "last_lifecycle_dispatch_generation"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_agent_runtimes_lifecycle_dispatch",
        table_name="agent_runtimes",
    )
    op.drop_column("agent_runtimes", "last_lifecycle_dispatch_generation")
