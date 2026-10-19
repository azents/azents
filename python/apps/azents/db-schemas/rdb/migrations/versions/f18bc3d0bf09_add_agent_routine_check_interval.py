"""Add the Agent-owned Routine checking interval."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f18bc3d0bf09"
down_revision: str | Sequence[str] | None = "00a4743d1962"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agents",
        sa.Column(
            "routine_check_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.create_check_constraint(
        "ck_agents_routine_check_interval_range",
        "agents",
        "routine_check_interval_minutes BETWEEN 1 AND 1440",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_agents_routine_check_interval_range", "agents", type_="check"
    )
    op.drop_column("agents", "routine_check_interval_minutes")
