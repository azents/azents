"""add skill loaded event kind

Revision ID: 6fdebb212632
Revises: 108ab194ee85
Create Date: 2026-07-02 08:32:25.516550

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6fdebb212632"
down_revision: str | Sequence[str] | None = "108ab194ee85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'skill_loaded'")


def downgrade() -> None:
    """Downgrade schema."""
