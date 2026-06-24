"""rename llm vendor terminology

Revision ID: 61faf051f9f3
Revises: a59d1439722a
Create Date: 2026-05-16 08:30:56.338798

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "61faf051f9f3"
down_revision: str | Sequence[str] | None = "a59d1439722a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename the column and enum to use LLM model developer terminology."""
    op.alter_column("llm_models", "vendor", new_column_name="model_developer")
    op.execute("ALTER TYPE llm_vendor RENAME TO llm_model_developer")


def downgrade() -> None:
    """Revert the LLM model developer terminology change."""
    op.execute("ALTER TYPE llm_model_developer RENAME TO llm_vendor")
    op.alter_column("llm_models", "model_developer", new_column_name="vendor")
