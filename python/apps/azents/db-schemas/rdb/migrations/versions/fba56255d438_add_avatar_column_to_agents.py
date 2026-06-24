"""add avatar column to agents

Revision ID: fba56255d438
Revises: 64fc6b946239
Create Date: 2026-04-21 06:52:28.344238

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fba56255d438"
down_revision: str | Sequence[str] | None = "64fc6b946239"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "avatar",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "avatar")
