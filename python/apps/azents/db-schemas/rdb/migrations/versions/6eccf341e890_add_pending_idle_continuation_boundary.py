"""add pending idle continuation boundary

Revision ID: 6eccf341e890
Revises: 8e053a554676
Create Date: 2026-07-21 17:10:43.390000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6eccf341e890"
down_revision: str | Sequence[str] | None = "8e053a554676"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_sessions",
        sa.Column(
            "pending_idle_continuation_run_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_agent_sessions_pending_idle_continuation_run_id_agent_runs",
        "agent_sessions",
        "agent_runs",
        ["pending_idle_continuation_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_agent_sessions_pending_idle_continuation_run_id_agent_runs",
        "agent_sessions",
        type_="foreignkey",
    )
    op.drop_column("agent_sessions", "pending_idle_continuation_run_id")
