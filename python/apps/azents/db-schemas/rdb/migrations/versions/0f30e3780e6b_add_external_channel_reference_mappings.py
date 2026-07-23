"""add external channel reference mappings

Revision ID: 0f30e3780e6b
Revises: 086a7982ed66
Create Date: 2026-07-23 03:20:32.081763

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0f30e3780e6b"
down_revision: str | Sequence[str] | None = "086a7982ed66"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "external_channel_message_revisions",
        sa.Column(
            "reference_mappings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("external_channel_message_revisions", "reference_mappings")
