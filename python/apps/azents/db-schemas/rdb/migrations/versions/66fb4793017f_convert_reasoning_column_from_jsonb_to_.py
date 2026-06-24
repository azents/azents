"""convert reasoning column from jsonb to text

Revision ID: 66fb4793017f
Revises: b2744e593076
Create Date: 2026-03-05 09:44:30.735892

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "66fb4793017f"
down_revision: str | Sequence[str] | None = "b2744e593076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add a temporary text column
    op.add_column("events", sa.Column("reasoning_text", sa.Text(), nullable=True))

    # 2. Extract text from existing JSONB and store it in the temporary column
    # OpenAI: {"summary": [{"text": "..."}]}
    # litellm: {"content": [{"text": "..."}]}
    op.execute(
        sa.text("""
        UPDATE events
        SET reasoning_text = (
            SELECT string_agg(elem->>'text', E'\\n')
            FROM jsonb_array_elements(
                COALESCE(reasoning->'summary', reasoning->'content')
            ) AS elem
            WHERE elem->>'text' IS NOT NULL AND elem->>'text' != ''
        )
        WHERE reasoning IS NOT NULL AND reasoning::text != 'null'
        """)
    )

    # 3. Drop the existing JSONB column
    op.drop_column("events", "reasoning")

    # 4. Rename the temporary column
    op.alter_column("events", "reasoning_text", new_column_name="reasoning")


def downgrade() -> None:
    """Downgrade schema."""
    # Restore text to jsonb. Text data is lost.
    op.alter_column(
        "events",
        "reasoning",
        existing_type=sa.Text(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=True,
        postgresql_using="NULL::jsonb",
    )
