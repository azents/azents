"""Separate Routine tick and minimum action delay."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e67a51c3c652"
down_revision: str | Sequence[str] | None = "f18bc3d0bf09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Transfer old tick into minimum delay before replacing tick."""
    op.add_column(
        "agents",
        sa.Column(
            "routine_min_action_delay_minutes",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE agents SET "
            "routine_min_action_delay_minutes = "
            "greatest(routine_check_interval_minutes, 30), "
            "routine_check_interval_minutes = "
            "greatest(routine_check_interval_minutes, 180)"
        )
    )
    op.drop_constraint(
        "ck_agents_routine_check_interval_range", "agents", type_="check"
    )
    op.create_check_constraint(
        "ck_agents_routine_check_interval_range",
        "agents",
        "routine_min_action_delay_minutes >= 30 "
        "AND routine_min_action_delay_minutes <= routine_check_interval_minutes "
        "AND routine_check_interval_minutes <= 1440",
    )
    op.alter_column("agents", "routine_check_interval_minutes", server_default="180")


def downgrade() -> None:
    """Restore the old contract without inventing historical tick values."""
    op.drop_constraint(
        "ck_agents_routine_check_interval_range", "agents", type_="check"
    )
    op.drop_column("agents", "routine_min_action_delay_minutes")
    op.create_check_constraint(
        "ck_agents_routine_check_interval_range",
        "agents",
        "routine_check_interval_minutes BETWEEN 1 AND 1440",
    )
    op.alter_column("agents", "routine_check_interval_minutes", server_default="30")
