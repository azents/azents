"""Remove google_search from supported_builtin_tools metadata.

Revision ID: bf99f7b4b6cc
Revises: c803e4022946
Create Date: 2026-03-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bf99f7b4b6cc"
down_revision: str | Sequence[str] | None = "c803e4022946"


def upgrade() -> None:
    """Remove the google_search item from metadata.supported_builtin_tools."""
    op.execute(
        sa.text("""
            UPDATE llm_provider_models
            SET metadata = jsonb_set(
                metadata,
                '{supported_builtin_tools}',
                (
                    SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                    FROM jsonb_array_elements_text(
                        metadata->'supported_builtin_tools'
                    ) AS elem
                    WHERE elem != 'google_search'
                )
            )
            WHERE metadata IS NOT NULL
              AND metadata ? 'supported_builtin_tools'
              AND metadata->'supported_builtin_tools' @> '"google_search"'
        """)
    )


def downgrade() -> None:
    """No-op because google_search cannot be restored."""
    pass
