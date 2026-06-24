"""add sdk run state column

Revision ID: e437f41e22c9
Revises: e14adf335c1d
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e437f41e22c9"
down_revision: str | Sequence[str] | None = "e14adf335c1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """conversation_sessions.sdk_run_state."""
    op.add_column(
        "conversation_sessions",
        sa.Column(
            "sdk_run_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("conversation_sessions", "sdk_run_state")
