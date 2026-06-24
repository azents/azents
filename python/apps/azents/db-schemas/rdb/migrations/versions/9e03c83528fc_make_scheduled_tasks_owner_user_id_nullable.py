"""make scheduled_tasks owner_user_id nullable

Revision ID: 9e03c83528fc
Revises: 0e5d7e370eda
Create Date: 2026-04-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9e03c83528fc"
down_revision: str | None = "0e5d7e370eda"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "scheduled_tasks",
        "owner_user_id",
        existing_type=sa.String(32),
        nullable=True,
    )
    op.execute(
        "UPDATE scheduled_tasks SET owner_user_id = NULL WHERE owner_user_id = ''"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE scheduled_tasks SET owner_user_id = '' WHERE owner_user_id IS NULL"
    )
    op.alter_column(
        "scheduled_tasks",
        "owner_user_id",
        existing_type=sa.String(32),
        nullable=False,
    )
