"""add run complete event type

Revision ID: 6308254dd81b
Revises: fbd2146851aa
Create Date: 2026-05-01 15:45:42.288407

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6308254dd81b"
down_revision: str | Sequence[str] | None = "fbd2146851aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'run_complete'")


def downgrade() -> None:
    """Downgrade schema."""
    pass
