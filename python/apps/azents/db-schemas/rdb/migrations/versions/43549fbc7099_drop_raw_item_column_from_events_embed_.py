"""drop raw_item column from events, embed raw in item

Revision ID: 43549fbc7099
Revises: 8008ccd1ddfd
Create Date: 2026-04-30 10:22:20.309634

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "43549fbc7099"
down_revision: str | Sequence[str] | None = "8008ccd1ddfd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Type ENUM groups for the events table, matching migration 8008ccd1ddfd.
# Used to recreate the CHECK constraint during downgrade.
_SDK_ORIGIN = (
    "text_item",
    "reasoning_item",
    "function_call_item",
    "function_call_output_item",
    "web_search_call_item",
    "image_generation_item",
    "unknown_item",
)
_AZ_ORIGIN = (
    "user_input",
    "system_reminder",
    "compaction",
    "turn_complete",
    "compaction_started",
    "subagent_start",
    "subagent_end",
    "error",
)


def upgrade() -> None:
    """Inline the raw_item column into the ``item.raw`` key and drop the column.

    1. Migrate UNKNOWN_ITEM rows where raw_item.role == 'user' to USER_INPUT.
       These are legacy chatcmpl_converter UserError traces where user messages
       entered as SDK unknown rows. The new schema normalizes them as USER_INPUT.
    2. Backfill raw_item from SDK-origin rows into item['raw'].
    3. Drop the raw_item column.

    Step 1 changes the type from SDK origin to Azents origin and violates the
    raw_item_invariant CHECK, so drop the CHECK before UPDATE.
    """
    op.drop_constraint("raw_item_invariant", "events", type_="check")

    op.execute(
        sa.text(
            """
            UPDATE events
            SET type = 'user_input',
                raw_item = NULL,
                item = jsonb_build_object(
                    'type', 'user_input',
                    'content', COALESCE(
                        CASE
                            WHEN jsonb_typeof(raw_item->'content') = 'string'
                                THEN raw_item->>'content'
                            WHEN jsonb_typeof(raw_item->'content') = 'array'
                                THEN COALESCE(
                                    (
                                        SELECT string_agg(
                                            part->>'text',
                                            E'\n'
                                        )
                                        FROM jsonb_array_elements(raw_item->'content')
                                            part
                                        WHERE part->>'type' IN ('input_text', 'text')
                                    ),
                                    ''
                                )
                            ELSE ''
                        END,
                        ''
                    ),
                    'headers', '[]'::jsonb,
                    'metadata', '{}'::jsonb,
                    'attachments', '[]'::jsonb,
                    'images', COALESCE(
                        CASE
                            WHEN jsonb_typeof(raw_item->'content') = 'array'
                                THEN (
                                    SELECT jsonb_agg(
                                        jsonb_build_object('url', part->>'image_url')
                                    )
                                    FROM jsonb_array_elements(raw_item->'content') part
                                    WHERE part->>'type' = 'input_image'
                                )
                            ELSE NULL
                        END,
                        '[]'::jsonb
                    )
                )
            WHERE type = 'unknown_item'
              AND raw_item ->> 'role' = 'user'
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE events
            SET item = item || jsonb_build_object('raw', raw_item)
            WHERE raw_item IS NOT NULL
            """
        )
    )

    op.drop_column("events", "raw_item")


def downgrade() -> None:
    """Split ``item.raw`` back into the raw_item column and recreate the CHECK.

    UNKNOWN_ITEM normalization is irreversible without losing the original raw_item,
    so rows restored to USER_INPUT during upgrade remain USER_INPUT.
    This does not affect raw_item invariant recreation because USER_INPUT is
    Azents origin.
    """
    # Recreate the raw_item column as nullable.
    op.add_column(
        "events",
        sa.Column(
            "raw_item",
            sa.dialects.postgresql.JSONB(),  # type: ignore[attr-defined]
            nullable=True,
        ),
    )

    # Split item['raw'] into raw_item and remove the 'raw' key from item.
    op.execute(
        sa.text(
            """
            UPDATE events
            SET raw_item = item->'raw',
                item = item - 'raw'
            WHERE item ? 'raw'
            """
        )
    )

    # Recreate CHECK.
    sdk_values = ", ".join(f"'{v}'" for v in sorted(_SDK_ORIGIN))
    azents_values = ", ".join(f"'{v}'" for v in sorted(_AZ_ORIGIN))
    op.create_check_constraint(
        "raw_item_invariant",
        "events",
        f"(type::text IN ({sdk_values}) AND raw_item IS NOT NULL) "
        f"OR (type::text IN ({azents_values}) AND raw_item IS NULL)",
    )
