"""add exchange file lifecycle metadata

Revision ID: c5f270fb34b3
Revises: 2c64d8eaf5b1
Create Date: 2026-06-03 01:34:04.436980

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c5f270fb34b3"
down_revision: str | Sequence[str] | None = "2c64d8eaf5b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    exchange_file_status = postgresql.ENUM(
        "available",
        "expired",
        name="exchange_file_status",
    )
    exchange_file_status.create(op.get_bind(), checkfirst=True)
    exchange_file_status_column = postgresql.ENUM(
        "available",
        "expired",
        name="exchange_file_status",
        create_type=False,
    )
    op.add_column(
        "exchange_files",
        sa.Column(
            "status",
            exchange_file_status_column,
            server_default="available",
            nullable=False,
        ),
    )
    op.add_column(
        "exchange_files",
        sa.Column("preview_title", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "exchange_files",
        sa.Column("preview_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "exchange_files",
        sa.Column(
            "preview_thumbnail_media_type",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "exchange_files",
        sa.Column("preview_thumbnail_width", sa.Integer(), nullable=True),
    )
    op.add_column(
        "exchange_files",
        sa.Column("preview_thumbnail_height", sa.Integer(), nullable=True),
    )
    op.add_column(
        "exchange_files",
        sa.Column("preview_generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "exchange_files",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now() + interval '30 days'"),
            nullable=False,
        ),
    )
    op.add_column(
        "exchange_files",
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_exchange_files_status_expires_at",
        "exchange_files",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_exchange_files_status_expires_at", table_name="exchange_files")
    op.drop_column("exchange_files", "expired_at")
    op.drop_column("exchange_files", "expires_at")
    op.drop_column("exchange_files", "preview_generated_at")
    op.drop_column("exchange_files", "preview_thumbnail_height")
    op.drop_column("exchange_files", "preview_thumbnail_width")
    op.drop_column("exchange_files", "preview_thumbnail_media_type")
    op.drop_column("exchange_files", "preview_summary")
    op.drop_column("exchange_files", "preview_title")
    op.drop_column("exchange_files", "status")
    postgresql.ENUM(name="exchange_file_status").drop(op.get_bind(), checkfirst=True)
