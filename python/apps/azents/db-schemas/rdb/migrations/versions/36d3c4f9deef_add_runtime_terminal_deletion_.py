"""add runtime terminal deletion acknowledgement."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "36d3c4f9deef"
down_revision: str | Sequence[str] | None = "9f6f27ecb54b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runtimes",
        sa.Column("terminal_delete_requested_generation", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "terminal_delete_acknowledged_generation",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "terminal_delete_acknowledged_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_runtimes", "terminal_delete_acknowledged_at")
    op.drop_column("agent_runtimes", "terminal_delete_acknowledged_generation")
    op.drop_column("agent_runtimes", "terminal_delete_requested_generation")
