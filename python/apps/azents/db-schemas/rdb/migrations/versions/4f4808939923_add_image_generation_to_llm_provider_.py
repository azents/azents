"""add image_generation to llm_provider_models

Revision ID: 4f4808939923
Revises: 763f0bc4493c
Create Date: 2026-03-04 00:03:35.371571

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4f4808939923"
down_revision: str | Sequence[str] | None = "763f0bc4493c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the image_generation column to the llm_provider_models table."""
    op.add_column(
        "llm_provider_models",
        sa.Column(
            "image_generation",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    """Remove the image_generation column from the llm_provider_models table."""
    op.drop_column("llm_provider_models", "image_generation")
