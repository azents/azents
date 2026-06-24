"""add agent max turns

Revision ID: 31222c42bd84
Revises: ba04afb397e8
Create Date: 2026-05-18 22:59:46.699467

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "31222c42bd84"
down_revision: str = "ba04afb397e8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("max_turns", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_agents_max_turns_positive",
        "agents",
        "max_turns IS NULL OR max_turns > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agents_max_turns_positive", "agents", type_="check")
    op.drop_column("agents", "max_turns")
