"""add events_v2 table for openai-events-redesign

Revision ID: e14adf335c1d
Revises: 9e03c83528fc
Create Date: 2026-04-28 16:55:25.233667
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e14adf335c1d"
down_revision: str | Sequence[str] | None = "9e03c83528fc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# type ENUM values for events_v2, one-to-one with EventType in core/enums.py.
# 7 SDK-origin values with raw_data NOT NULL + 8 Azents values with raw_data NULL = 15.
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
    """Create the events_v2 table and event_type ENUM."""
    event_type = postgresql.ENUM(
        *_SDK_ORIGIN,
        *_AZ_ORIGIN,
        name="event_type",
    )
    event_type.create(op.get_bind(), checkfirst=False)

    sdk_values = ", ".join(f"'{v}'" for v in sorted(_SDK_ORIGIN))
    azents_values = ", ".join(f"'{v}'" for v in sorted(_AZ_ORIGIN))

    op.create_table(
        "events_v2",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "type",
            postgresql.ENUM(
                *_SDK_ORIGIN,
                *_AZ_ORIGIN,
                name="event_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["conversation_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"(type::text IN ({sdk_values}) AND raw_data IS NOT NULL) "
            f"OR (type::text IN ({azents_values}) AND raw_data IS NULL)",
            name="raw_data_invariant",
        ),
    )
    op.create_index(
        "ix_events_v2_session_id",
        "events_v2",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_events_v2_session_created",
        "events_v2",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_events_v2_session_external",
        "events_v2",
        ["session_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the events_v2 table and event_type ENUM."""
    op.drop_index("uq_events_v2_session_external", table_name="events_v2")
    op.drop_index("ix_events_v2_session_created", table_name="events_v2")
    op.drop_index("ix_events_v2_session_id", table_name="events_v2")
    op.drop_table("events_v2")

    event_type = postgresql.ENUM(name="event_type")
    event_type.drop(op.get_bind(), checkfirst=False)
