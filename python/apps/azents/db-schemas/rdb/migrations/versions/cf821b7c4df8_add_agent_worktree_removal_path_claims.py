"""add agent worktree removal path claims

Revision ID: cf821b7c4df8
Revises: 0a534149c228
Create Date: 2026-08-12 15:02:29.266221

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cf821b7c4df8"
down_revision: str | Sequence[str] | None = "0a534149c228"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TYPE git_worktree_path_claim_owner_kind "
        "ADD VALUE IF NOT EXISTS 'agent_action'"
    )


def downgrade() -> None:
    """Downgrade schema."""
