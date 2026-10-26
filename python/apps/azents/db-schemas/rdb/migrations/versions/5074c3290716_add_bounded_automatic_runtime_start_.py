"""add bounded automatic runtime start receipt

Revision ID: 5074c3290716
Revises: 0701fb42b5ce
Create Date: 2026-10-26 08:39:49.655271

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5074c3290716"
down_revision: str | Sequence[str] | None = "0701fb42b5ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "automatic_start_predecessor_sequence", sa.BigInteger(), nullable=True
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "automatic_start_predecessor_generation", sa.Integer(), nullable=True
        ),
    )
    op.create_check_constraint(
        "ck_agent_runtimes_automatic_start_receipt",
        "agent_runtimes",
        "(automatic_start_predecessor_sequence IS NULL "
        "AND automatic_start_predecessor_generation IS NULL) OR "
        "(automatic_start_predecessor_sequence >= 1 "
        "AND automatic_start_predecessor_generation >= 0 "
        "AND automatic_start_predecessor_sequence IS NOT NULL "
        "AND automatic_start_predecessor_generation IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_agent_runtimes_automatic_start_receipt", "agent_runtimes", type_="check"
    )
    op.drop_column("agent_runtimes", "automatic_start_predecessor_generation")
    op.drop_column("agent_runtimes", "automatic_start_predecessor_sequence")
