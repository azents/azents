"""add session title

Revision ID: fea922c9bf44
Revises: 97d069ea543b
Create Date: 2026-03-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fea922c9bf44"
down_revision: str | None = "97d069ea543b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_sessions",
        sa.Column("title", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_sessions", "title")
