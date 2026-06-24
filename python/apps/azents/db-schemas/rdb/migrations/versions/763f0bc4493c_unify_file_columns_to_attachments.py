"""unify_file_columns_to_attachments

Unify inbox_files, outbox_files, and thumbnails columns into attachments.

Revision ID: 763f0bc4493c
Revises: 7c99853a1843
Create Date: 2026-03-02 12:42:15.451288

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "763f0bc4493c"
down_revision: str | Sequence[str] | None = "7c99853a1843"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Unify inbox_files, outbox_files, and thumbnails into attachments."""
    # 1. Add the attachments column
    op.add_column("events", sa.Column("attachments", JSONB, nullable=True))

    # 2. Migrate existing data
    #    Merge inbox_files and outbox_files into attachments
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE events
            SET attachments = COALESCE(inbox_files, '[]'::jsonb)
                              || COALESCE(outbox_files, '[]'::jsonb)
            WHERE inbox_files IS NOT NULL OR outbox_files IS NOT NULL
        """)
    )

    # 3. Drop previous columns
    op.drop_column("events", "thumbnails")
    op.drop_column("events", "outbox_files")
    op.drop_column("events", "inbox_files")


def downgrade() -> None:
    """Restore attachments to inbox_files, outbox_files, and thumbnails columns."""
    op.add_column("events", sa.Column("inbox_files", JSONB, nullable=True))
    op.add_column("events", sa.Column("outbox_files", JSONB, nullable=True))
    op.add_column("events", sa.Column("thumbnails", JSONB, nullable=True))
    op.drop_column("events", "attachments")
