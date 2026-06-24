"""add lifecycle columns to agents

Revision ID: c93117a5f231
Revises: c2ea1992a602
Create Date: 2026-04-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c93117a5f231"
down_revision: str | None = "c2ea1992a602"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("lifecycle_run_id", sa.String(80), nullable=True))
    op.add_column("agents", sa.Column("lifecycle_state", sa.String(20), nullable=True))
    op.add_column(
        "agents",
        sa.Column("lifecycle_claimed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "lifecycle_claimed_at")
    op.drop_column("agents", "lifecycle_state")
    op.drop_column("agents", "lifecycle_run_id")
