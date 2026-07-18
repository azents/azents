"""normalize provider tool semantic content

Revision ID: 25bc37eadace
Revises: d54f4767b88e
Create Date: 2026-07-18 12:38:58.172225

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "25bc37eadace"
down_revision: str | Sequence[str] | None = "d54f4767b88e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace provider-tool positional fields with shared semantic content."""
    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = (payload - 'arguments') || jsonb_build_object(
                'status', COALESCE(payload->'status', 'null'::jsonb),
                'semantic', jsonb_build_object(
                    'input', COALESCE(payload->'arguments', 'null'::jsonb),
                    'output', '[]'::jsonb,
                    'references', '[]'::jsonb
                ),
                'attachments', '[]'::jsonb
            )
            WHERE kind = 'provider_tool_call'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = (payload - 'output') || jsonb_build_object(
                'name', COALESCE(payload->'name', 'null'::jsonb),
                'semantic', jsonb_build_object(
                    'input', 'null'::jsonb,
                    'output', COALESCE(payload->'output', '[]'::jsonb),
                    'references', '[]'::jsonb
                ),
                'attachments', COALESCE(payload->'attachments', '[]'::jsonb)
            )
            WHERE kind = 'provider_tool_result'
            """
        )
    )


def downgrade() -> None:
    """Restore the previous provider-tool call and result fields."""
    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = (payload - 'semantic' - 'attachments') || jsonb_build_object(
                'arguments', COALESCE(payload->'semantic'->'input', 'null'::jsonb)
            )
            WHERE kind = 'provider_tool_call'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = (payload - 'semantic') || jsonb_build_object(
                'output', COALESCE(payload->'semantic'->'output', '[]'::jsonb)
            )
            WHERE kind = 'provider_tool_result'
            """
        )
    )
