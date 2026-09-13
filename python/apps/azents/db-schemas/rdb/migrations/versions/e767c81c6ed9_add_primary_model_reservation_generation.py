"""Add a durable Primary model reservation generation."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e767c81c6ed9"
down_revision: str | Sequence[str] | None = "fae69c6c3540"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add and backfill the Session reservation generation high-water mark."""
    op.add_column(
        "agent_sessions",
        sa.Column(
            "primary_model_reservation_generation",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE agent_sessions
        SET primary_model_reservation_generation =
            (primary_model_reservation ->> 'reservation_generation')::bigint
        WHERE primary_model_reservation IS NOT NULL
        """
    )


def downgrade() -> None:
    """Remove the Session reservation generation high-water mark."""
    op.drop_column("agent_sessions", "primary_model_reservation_generation")
