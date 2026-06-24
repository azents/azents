"""add runtime provider observe timestamps

Revision ID: 4b6e803cae38
Revises: 6b1f0e2a9c73
Create Date: 2026-05-26 09:10:34.952227

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4b6e803cae38"
down_revision: str | Sequence[str] | None = "6b1f0e2a9c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runtimes",
        sa.Column("provider_observed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "provider_observe_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_agent_runtimes_provider_observe_requested_at",
        "agent_runtimes",
        ["provider_observe_requested_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_agent_runtimes_provider_observe_requested_at",
        table_name="agent_runtimes",
    )
    op.drop_column("agent_runtimes", "provider_observe_requested_at")
    op.drop_column("agent_runtimes", "provider_observed_at")
