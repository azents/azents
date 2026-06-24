"""delete invalid canonical turn usage

Revision ID: 3758f4f8112a
Revises: 29d80393ae0e
Create Date: 2026-05-28 19:53:32.124834

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3758f4f8112a"
down_revision: str | Sequence[str] | None = "29d80393ae0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Delete canonical turn usage markers stored without raw usage."""
    op.execute(
        """
        DELETE FROM events
        WHERE kind = 'turn_marker'
          AND (
            NOT (payload ? 'usage')
            OR payload->'usage' = 'null'::jsonb
            OR jsonb_typeof(payload->'usage') <> 'object'
            OR NOT (payload->'usage' ? 'prompt_tokens')
            OR jsonb_typeof(payload->'usage'->'prompt_tokens') <> 'number'
            OR NOT (payload->'usage' ? 'completion_tokens')
            OR jsonb_typeof(payload->'usage'->'completion_tokens') <> 'number'
            OR NOT (payload->'usage' ? 'total_tokens')
            OR jsonb_typeof(payload->'usage'->'total_tokens') <> 'number'
            OR NOT (payload->'usage' ? 'raw')
            OR payload->'usage'->'raw' = 'null'::jsonb
            OR jsonb_typeof(payload->'usage'->'raw') <> 'object'
          )
        """
    )


def downgrade() -> None:
    """Deleted invalid turn markers cannot be restored."""
    pass
