"""add summary to scheduled_tasks

Revision ID: a4232f31bc4b
Revises: c6ef061e5744
Create Date: 2026-04-01 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4232f31bc4b"
down_revision: str | Sequence[str] | None = "c6ef061e5744"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scheduled_tasks",
        sa.Column(
            "summary",
            sa.String(length=100),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("scheduled_tasks", "summary")
