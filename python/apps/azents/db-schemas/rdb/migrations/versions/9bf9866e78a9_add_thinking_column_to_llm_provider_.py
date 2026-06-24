"""add thinking column to llm_provider_models

Revision ID: 9bf9866e78a9
Revises: 4f4808939923
Create Date: 2026-03-04 10:28:54.529675

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9bf9866e78a9"
down_revision: str | Sequence[str] | None = "4f4808939923"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "llm_provider_models",
        sa.Column("thinking", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("llm_provider_models", "thinking")
