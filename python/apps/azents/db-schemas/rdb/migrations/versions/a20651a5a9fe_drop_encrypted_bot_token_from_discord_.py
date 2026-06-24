"""drop encrypted_bot_token from discord_installations.

Revision ID: a20651a5a9fe
Revises: b296fd1442c0
Create Date: 2026-03-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a20651a5a9fe"
down_revision: str | None = "b296fd1442c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("discord_installations", "encrypted_bot_token")


def downgrade() -> None:
    op.add_column(
        "discord_installations",
        sa.Column("encrypted_bot_token", sa.Text, nullable=False, server_default=""),
    )
