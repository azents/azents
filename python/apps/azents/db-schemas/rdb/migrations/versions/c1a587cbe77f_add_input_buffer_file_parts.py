"""add input buffer file parts

Revision ID: c1a587cbe77f
Revises: 9dce16e965dc
Create Date: 2026-06-03 11:07:32.514776

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c1a587cbe77f"
down_revision: str | Sequence[str] | None = "9dce16e965dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add independent FilePart snapshots to InputBuffer."""
    op.add_column(
        "input_buffers",
        sa.Column(
            "file_parts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column("input_buffers", "file_parts", server_default=None)


def downgrade() -> None:
    """Remove InputBuffer FilePart snapshots."""
    op.drop_column("input_buffers", "file_parts")
