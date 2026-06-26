"""add file blob deletion markers

Revision ID: f3c06dfb5496
Revises: 9779e2e7f451
Create Date: 2026-06-26 19:18:51.279473

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c06dfb5496"
down_revision: str | Sequence[str] | None = "9779e2e7f451"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "exchange_files",
        sa.Column("blob_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "artifacts",
        sa.Column("blob_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "model_files",
        sa.Column("blob_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("model_files", "blob_deleted_at")
    op.drop_column("artifacts", "blob_deleted_at")
    op.drop_column("exchange_files", "blob_deleted_at")
