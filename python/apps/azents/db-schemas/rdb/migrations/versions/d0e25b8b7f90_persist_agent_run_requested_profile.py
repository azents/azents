"""persist agent run requested profile

Revision ID: d0e25b8b7f90
Revises: 936373d16d53
Create Date: 2026-08-20 00:38:41.323819

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d0e25b8b7f90"
down_revision: str | Sequence[str] | None = "936373d16d53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Restore run-bound requested inference profile for recovery."""
    op.add_column(
        "agent_runs",
        sa.Column("requested_model_target_label", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "requested_reasoning_effort",
            postgresql.ENUM(
                "none",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
                name="model_reasoning_effort",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_agent_runs_requested_profile",
        "agent_runs",
        "requested_reasoning_effort IS NULL "
        "OR requested_model_target_label IS NOT NULL",
    )


def downgrade() -> None:
    """Remove run-bound requested inference profile."""
    op.drop_constraint("ck_agent_runs_requested_profile", "agent_runs", type_="check")
    op.drop_column("agent_runs", "requested_reasoning_effort")
    op.drop_column("agent_runs", "requested_model_target_label")
