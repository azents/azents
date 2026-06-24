"""add agent session lifecycle marker

Revision ID: ba04afb397e8
Revises: f03e260c501c
Create Date: 2026-05-18 06:10:41.570690

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

from azents.rdb.types.datetime import TimeZoneDateTime

# revision identifiers, used by Alembic.
revision: str = "ba04afb397e8"
down_revision: str | Sequence[str] | None = "f03e260c501c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_sessions",
        sa.Column(
            "lifecycle_started_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_sessions", "lifecycle_started_at")
