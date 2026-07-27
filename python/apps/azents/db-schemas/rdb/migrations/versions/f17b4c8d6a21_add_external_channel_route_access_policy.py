"""add external channel route access policy

Revision ID: f17b4c8d6a21
Revises: e0615474dc27
Create Date: 2026-07-27 06:30:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f17b4c8d6a21"
down_revision: str | Sequence[str] | None = "e0615474dc27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "external_channel_agent_routes",
        sa.Column(
            "open_access_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "external_channel_agent_routes",
        sa.Column(
            "allow_bot_messages",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("external_channel_agent_routes", "allow_bot_messages")
    op.drop_column("external_channel_agent_routes", "open_access_enabled")
