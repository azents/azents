"""add model call start time to agent runs

Revision ID: 7d01fb472aeb
Revises: 4ac866c17faf
Create Date: 2026-07-14 08:32:48.290283

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7d01fb472aeb"
down_revision: str | Sequence[str] | None = "4ac866c17faf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runs",
        sa.Column("model_call_started_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_runs", "model_call_started_at")
