"""enable tool search by default

Revision ID: c4e49a389b5c
Revises: 6b4ed906ae81
Create Date: 2026-07-21 06:28:55.409078

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e49a389b5c"
down_revision: str | Sequence[str] | None = "6b4ed906ae81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "agents",
        "tool_search_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.text("true"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "agents",
        "tool_search_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.text("false"),
    )
