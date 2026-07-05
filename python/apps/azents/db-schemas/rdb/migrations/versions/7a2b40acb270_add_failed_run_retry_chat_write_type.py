"""add failed run retry chat write type

Revision ID: 7a2b40acb270
Revises: a3abe5d1a632
Create Date: 2026-07-05 01:56:36.278688

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a2b40acb270"
down_revision: str | Sequence[str] | None = "a3abe5d1a632"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TYPE chat_write_request_type ADD VALUE IF NOT EXISTS 'failed_run_retry'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    pass
