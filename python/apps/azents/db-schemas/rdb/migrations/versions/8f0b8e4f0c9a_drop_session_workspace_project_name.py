"""drop session workspace project name

Revision ID: 8f0b8e4f0c9a
Revises: 2a67b2860503
Create Date: 2026-06-11 02:40:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f0b8e4f0c9a"
down_revision: str | Sequence[str] | None = "2a67b2860503"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("session_workspace_projects", "name")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "session_workspace_projects",
        sa.Column(
            "name",
            sa.String(length=255),
            server_default=sa.text("'Project'"),
            nullable=False,
        ),
    )
    op.alter_column("session_workspace_projects", "name", server_default=None)
