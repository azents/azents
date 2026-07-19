"""use single provider tool events

Revision ID: e95f7e9143c5
Revises: 25bc37eadace
Create Date: 2026-07-19 07:44:01.052354

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e95f7e9143c5"
down_revision: str | Sequence[str] | None = "25bc37eadace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_KIND_VALUES = (
    "user_message",
    "goal_continuation",
    "goal_updated",
    "action_message",
    "agent_message",
    "action_execution_result",
    "skill_loaded",
    "goal_briefing",
    "assistant_message",
    "reasoning",
    "client_tool_call",
    "client_tool_result",
    "provider_tool_call",
    "turn_marker",
    "run_marker",
    "interrupted",
    "compaction_marker",
    "compaction_summary",
    "system_reminder",
    "system_error",
    "unknown_adapter_output",
)
_EVENT_KIND_VALUES_WITH_PROVIDER_RESULT = (
    *_EVENT_KIND_VALUES[:13],
    "provider_tool_result",
    *_EVENT_KIND_VALUES[13:],
)


def _replace_event_kind(values: Sequence[str]) -> None:
    quoted_values = ", ".join(f"'{value}'" for value in values)
    op.execute(sa.text(f"CREATE TYPE event_kind_new AS ENUM ({quoted_values})"))
    op.execute(
        sa.text(
            "ALTER TABLE events ALTER COLUMN kind TYPE event_kind_new "
            "USING kind::text::event_kind_new"
        )
    )
    op.execute(sa.text("DROP TYPE event_kind"))
    op.execute(sa.text("ALTER TYPE event_kind_new RENAME TO event_kind"))


def upgrade() -> None:
    """Unify provider events and move tool attachments into output parts."""
    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = jsonb_set(
                payload - 'attachments',
                '{semantic,output}',
                CASE jsonb_typeof(payload->'semantic'->'output')
                    WHEN 'array' THEN payload->'semantic'->'output'
                    WHEN 'string' THEN jsonb_build_array(jsonb_build_object(
                        'type', 'text',
                        'text', payload->'semantic'->'output'
                    ))
                    ELSE '[]'::jsonb
                END || COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object('type', 'attachment')
                        || (attachment - 'created_at' - 'source')
                    )
                    FROM jsonb_array_elements(
                        COALESCE(payload->'attachments', '[]'::jsonb)
                    ) AS attachment
                ), '[]'::jsonb),
                true
            )
            WHERE kind IN ('provider_tool_call', 'provider_tool_result')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = jsonb_set(
                    payload,
                    '{name}',
                    to_jsonb(COALESCE(payload->>'name', 'image_generation')),
                    true
                ),
                kind = 'provider_tool_call'
            WHERE kind = 'provider_tool_result'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = jsonb_set(
                payload - 'attachments',
                '{output}',
                CASE jsonb_typeof(payload->'output')
                    WHEN 'array' THEN payload->'output'
                    WHEN 'string' THEN jsonb_build_array(jsonb_build_object(
                        'type', 'text',
                        'text', payload->'output'
                    ))
                    ELSE '[]'::jsonb
                END || COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object('type', 'attachment')
                        || (attachment - 'created_at' - 'source')
                    )
                    FROM jsonb_array_elements(
                        COALESCE(payload->'attachments', '[]'::jsonb)
                    ) AS attachment
                ), '[]'::jsonb),
                true
            )
            WHERE kind = 'client_tool_result'
            """
        )
    )
    _replace_event_kind(_EVENT_KIND_VALUES)


def downgrade() -> None:
    """Restore provider result events and top-level tool attachments."""
    _replace_event_kind(_EVENT_KIND_VALUES_WITH_PROVIDER_RESULT)
    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = jsonb_set(
                    jsonb_set(
                        payload,
                        '{semantic,output}',
                        COALESCE((
                            SELECT jsonb_agg(part)
                            FROM jsonb_array_elements(
                                CASE jsonb_typeof(payload->'semantic'->'output')
                                    WHEN 'array' THEN payload->'semantic'->'output'
                                    ELSE '[]'::jsonb
                                END
                            ) AS part
                            WHERE part->>'type' <> 'attachment'
                        ), '[]'::jsonb),
                        true
                    ),
                    '{attachments}',
                    COALESCE((
                        SELECT jsonb_agg(
                            (part - 'type')
                            || jsonb_build_object(
                                'created_at', to_jsonb(events.created_at),
                                'source', 'provider_tool'
                            )
                        )
                        FROM jsonb_array_elements(
                            CASE jsonb_typeof(payload->'semantic'->'output')
                                WHEN 'array' THEN payload->'semantic'->'output'
                                ELSE '[]'::jsonb
                            END
                        ) AS part
                        WHERE part->>'type' = 'attachment'
                    ), '[]'::jsonb),
                    true
                ),
                kind = CASE
                    WHEN payload->>'name' = 'image_generation'
                        AND payload->'native_artifact'->'item'->>'type'
                            = 'image_generation_call'
                    THEN 'provider_tool_result'::event_kind
                    ELSE kind
                END
            WHERE kind = 'provider_tool_call'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = jsonb_set(
                payload,
                '{status}',
                '"interrupted"'::jsonb,
                true
            )
            WHERE kind = 'provider_tool_result'
              AND (
                  payload->>'status' IS NULL
                  OR payload->>'status' NOT IN (
                      'completed',
                      'failed',
                      'cancelled',
                      'interrupted'
                  )
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = jsonb_set(
                payload,
                '{status}',
                '"failed"'::jsonb,
                true
            )
            WHERE kind = 'provider_tool_call'
              AND payload->>'status' IN ('cancelled', 'interrupted')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = jsonb_set(
                jsonb_set(
                    payload,
                    '{output}',
                    COALESCE((
                        SELECT jsonb_agg(part)
                        FROM jsonb_array_elements(
                            CASE jsonb_typeof(payload->'output')
                                WHEN 'array' THEN payload->'output'
                                ELSE '[]'::jsonb
                            END
                        ) AS part
                        WHERE part->>'type' <> 'attachment'
                    ), '[]'::jsonb),
                    true
                ),
                '{attachments}',
                COALESCE((
                    SELECT jsonb_agg(
                        (part - 'type')
                        || jsonb_build_object(
                            'created_at', to_jsonb(events.created_at),
                            'source', 'client_tool'
                        )
                    )
                    FROM jsonb_array_elements(
                        CASE jsonb_typeof(payload->'output')
                            WHEN 'array' THEN payload->'output'
                            ELSE '[]'::jsonb
                        END
                    ) AS part
                    WHERE part->>'type' = 'attachment'
                ), '[]'::jsonb),
                true
            )
            WHERE kind = 'client_tool_result'
            """
        )
    )
