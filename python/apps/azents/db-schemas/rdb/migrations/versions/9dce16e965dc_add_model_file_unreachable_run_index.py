"""add model file unreachable run index

Revision ID: 9dce16e965dc
Revises: c5f270fb34b3
Create Date: 2026-06-03 02:06:21.809847

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9dce16e965dc"
down_revision: str | Sequence[str] | None = "c5f270fb34b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ModelFile unreachable transition metadata."""
    op.add_column(
        "model_files",
        sa.Column("unreachable_run_index", sa.Integer(), nullable=True),
    )
    op.add_column(
        "model_files",
        sa.Column("unreachable_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_model_files_unreachable_gc",
        "model_files",
        ["session_id", "status", "unreachable_run_index"],
    )


def downgrade() -> None:
    """Remove ModelFile unreachable transition metadata."""
    op.drop_index("ix_model_files_unreachable_gc", table_name="model_files")
    op.drop_column("model_files", "unreachable_at")
    op.drop_column("model_files", "unreachable_run_index")
