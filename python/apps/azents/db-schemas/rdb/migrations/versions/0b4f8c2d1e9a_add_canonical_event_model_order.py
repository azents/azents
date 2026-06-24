"""add canonical event model order

Revision ID: 0b4f8c2d1e9a
Revises: 9b9479c34ec7
Create Date: 2026-05-30 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0b4f8c2d1e9a"
down_revision: str | Sequence[str] | None = "9b9479c34ec7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add logical input order for canonical event models."""
    op.add_column("events", sa.Column("model_order", sa.BigInteger(), nullable=True))
    op.execute(
        sa.text(
            """
            WITH ordered AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY session_id
                        ORDER BY id ASC
                    ) * 1000 AS model_order
                FROM events
            )
            UPDATE events
            SET model_order = ordered.model_order
            FROM ordered
            WHERE events.id = ordered.id
            """
        )
    )
    op.alter_column("events", "model_order", nullable=False)
    op.create_index(
        "ix_events_session_model_order",
        "events",
        ["session_id", "model_order"],
        unique=True,
    )


def downgrade() -> None:
    """Remove logical input order for canonical event models."""
    op.drop_index("ix_events_session_model_order", table_name="events")
    op.drop_column("events", "model_order")
