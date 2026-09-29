"""retain completed exchange upload cleanup ownership

Revision ID: 0c18705eb6cb
Revises: 9462aab292cc
Create Date: 2026-09-29 22:14:09.328095

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0c18705eb6cb"
down_revision: str | Sequence[str] | None = "9462aab292cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Index completed operations for recurring physical residue cleanup."""
    op.drop_index(
        "ix_exchange_upload_operations_due_cleanup",
        table_name="exchange_upload_operations",
    )
    op.create_index(
        "ix_exchange_upload_operations_due_cleanup",
        "exchange_upload_operations",
        ["cleanup_after", "cleanup_lease_until", "id"],
    )


def downgrade() -> None:
    """Restore the initial incomplete-operation cleanup index."""
    op.drop_index(
        "ix_exchange_upload_operations_due_cleanup",
        table_name="exchange_upload_operations",
    )
    op.create_index(
        "ix_exchange_upload_operations_due_cleanup",
        "exchange_upload_operations",
        ["cleanup_after", "cleanup_lease_until", "id"],
        postgresql_where=sa.text("cleanup_completed_at IS NULL"),
    )
