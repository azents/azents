"""add exchange file preview thumbnail reference

Revision ID: b9d4a6c13e52
Revises: 74d24674441d
Create Date: 2026-06-02 18:20:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9d4a6c13e52"
down_revision: str | Sequence[str] | None = "74d24674441d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a preview thumbnail file reference to the original ExchangeFile row."""
    op.add_column(
        "exchange_files",
        sa.Column("preview_thumbnail_file_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_exchange_files_preview_thumbnail_file_id",
        "exchange_files",
        "exchange_files",
        ["preview_thumbnail_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_exchange_files_preview_thumbnail_file_id",
        "exchange_files",
        ["preview_thumbnail_file_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the ExchangeFile preview thumbnail file reference."""
    op.drop_index(
        "ix_exchange_files_preview_thumbnail_file_id",
        table_name="exchange_files",
    )
    op.drop_constraint(
        "fk_exchange_files_preview_thumbnail_file_id",
        "exchange_files",
        type_="foreignkey",
    )
    op.drop_column("exchange_files", "preview_thumbnail_file_id")
