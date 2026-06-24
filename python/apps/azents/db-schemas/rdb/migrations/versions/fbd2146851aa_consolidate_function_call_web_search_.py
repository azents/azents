"""consolidate function_call/web_search into tool_call_item

Revision ID: fbd2146851aa
Revises: 43549fbc7099
Create Date: 2026-04-30 12:18:08.193128

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fbd2146851aa"
down_revision: str | Sequence[str] | None = "43549fbc7099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Consolidate function_call and web_search items into tool_call items.

    Combine ``function_call_item``, ``function_call_output_item``, and
    ``web_search_call_item`` into ``tool_call_item`` / ``tool_call_output_item``.
    Pydantic keeps only raw payloads without subtype-specific types, so combine
    the enum values as well.

    Procedure, using a new enum swap because Postgres ENUM ALTER is limited:
    1. Create new ``event_type_v2`` enum
    2. Convert ``events.type`` to v2 with rename and remap
    3. Promote ``call_id`` / ``name`` / ``arguments`` from existing ``item.raw``
       to top-level normalized fields in ``item`` for function calls only.
    4. Drop the existing ``event_type`` enum and rename v2 to ``event_type``
    """
    # 1. Create new enum
    op.execute(
        sa.text(
            """
            CREATE TYPE event_type_v2 AS ENUM (
                'text_item',
                'reasoning_item',
                'tool_call_item',
                'tool_call_output_item',
                'image_generation_item',
                'unknown_item',
                'user_input',
                'system_reminder',
                'compaction',
                'turn_complete',
                'compaction_started',
                'subagent_start',
                'subagent_end',
                'error'
            )
            """
        )
    )

    # 2. Convert function_call_item / web_search_call_item
    #    to tool_call_item,
    #    function_call_output_item → tool_call_output_item.
    op.execute(
        sa.text(
            """
            ALTER TABLE events
            ALTER COLUMN type TYPE event_type_v2 USING (
                CASE type::text
                    WHEN 'function_call_item' THEN 'tool_call_item'
                    WHEN 'web_search_call_item' THEN 'tool_call_item'
                    WHEN 'function_call_output_item' THEN 'tool_call_output_item'
                    ELSE type::text
                END
            )::event_type_v2
            """
        )
    )

    # 3. Promote normalized fields from item.raw to top-level item
    #    for function_call subtype rows.
    op.execute(
        sa.text(
            """
            UPDATE events
            SET item = item || jsonb_build_object(
                'call_id', COALESCE(
                    item->'raw'->>'call_id',
                    item->'raw'->>'id',
                    ''
                ),
                'name', COALESCE(
                    item->'raw'->>'name',
                    item->'raw'->>'type',
                    ''
                ),
                'arguments', COALESCE(item->'raw'->>'arguments', '')
            )
            WHERE type = 'tool_call_item'
            """
        )
    )

    # 3b. Normalize tool_call_output_item as structured output.
    #     Existing item may already contain call_id / output, but ensure consistency.
    op.execute(
        sa.text(
            """
            UPDATE events
            SET item = item || jsonb_build_object(
                'call_id', COALESCE(
                    item->>'call_id',
                    item->'raw'->>'call_id',
                    ''
                ),
                'output', COALESCE(
                    item->'output',
                    jsonb_build_object(
                        'content', COALESCE(item->'raw'->>'output', ''),
                        'attachments', '[]'::jsonb,
                        'images', '[]'::jsonb
                    )
                )
            )
            WHERE type = 'tool_call_output_item'
            """
        )
    )

    # 4. Drop old enum and rename.
    op.execute(sa.text("DROP TYPE event_type"))
    op.execute(sa.text("ALTER TYPE event_type_v2 RENAME TO event_type"))


def downgrade() -> None:
    """Revert tool_call_item / tool_call_output_item to function_call variants.

    Split web_search_call_item by inspecting raw.type.
    """
    op.execute(
        sa.text(
            """
            CREATE TYPE event_type_old AS ENUM (
                'text_item',
                'reasoning_item',
                'function_call_item',
                'function_call_output_item',
                'web_search_call_item',
                'image_generation_item',
                'unknown_item',
                'user_input',
                'system_reminder',
                'compaction',
                'turn_complete',
                'compaction_started',
                'subagent_start',
                'subagent_end',
                'error'
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            ALTER TABLE events
            ALTER COLUMN type TYPE event_type_old USING (
                CASE type::text
                    WHEN 'tool_call_item' THEN
                        CASE
                            WHEN item->'raw'->>'type' = 'web_search_call'
                                THEN 'web_search_call_item'
                            ELSE 'function_call_item'
                        END
                    WHEN 'tool_call_output_item' THEN 'function_call_output_item'
                    ELSE type::text
                END
            )::event_type_old
            """
        )
    )

    # Remove tool_call normalized fields from item, only for function_call rows.
    op.execute(
        sa.text(
            """
            UPDATE events
            SET item = item - 'call_id' - 'name' - 'arguments'
            WHERE type = 'function_call_item'
            """
        )
    )

    op.execute(sa.text("DROP TYPE event_type"))
    op.execute(sa.text("ALTER TYPE event_type_old RENAME TO event_type"))
