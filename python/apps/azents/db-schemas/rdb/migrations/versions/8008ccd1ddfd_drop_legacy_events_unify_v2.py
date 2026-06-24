"""drop legacy events table, rename events_v2 to events, item/raw_item columns

Revision ID: 8008ccd1ddfd
Revises: e437f41e22c9
Create Date: 2026-04-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8008ccd1ddfd"
down_revision: str | Sequence[str] | None = "e437f41e22c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# message_role enum values for the legacy events table.
# Used for empty downgrade restore.
_LEGACY_MESSAGE_ROLE_VALUES = (
    "system",
    "user",
    "assistant",
    "tool",
    "compaction",
    "compaction_started",
    "turn_complete",
    "subagent_start",
    "subagent_end",
)


# Type ENUM groups for the renamed events table. Same as _SDK_ORIGIN / _AZ_ORIGIN
# from events_v2 migration e14adf335c1d; used only to recreate the CHECK constraint.
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
    """Drop legacy events, rename events_v2 to events, and add source_model.

    Data loss is allowed because the events_v2 schema is the new source of truth.
    The drop, rename, and alter operations run in one transaction, so external
    readers never observe a missing events table.

    Steps:
      1. Drop legacy ``events`` table and indexes
      2. Drop legacy ``message_role`` ENUM
      3. Rename ``events_v2`` to ``events`` for the table and 3 indexes
      4. Rename ``data`` to ``item`` and ``raw_data`` to ``raw_item``
      5. Recreate ``raw_data_invariant`` CHECK referencing raw_item
      6. Add nullable ``source_model`` TEXT column
    """
    # 1) Drop legacy events table and indexes
    op.drop_index("ix_events_session_id", table_name="events")
    op.drop_table("events")

    # 2) Drop legacy message_role ENUM; no remaining usages
    sa.Enum(name="message_role").drop(op.get_bind(), checkfirst=True)

    # 3) Rename events_v2 to events for the table and indexes
    op.rename_table("events_v2", "events")
    op.execute("ALTER INDEX ix_events_v2_session_id RENAME TO ix_events_session_id")
    op.execute(
        "ALTER INDEX ix_events_v2_session_created RENAME TO ix_events_session_created"
    )
    op.execute(
        "ALTER INDEX uq_events_v2_session_external RENAME TO uq_events_session_external"
    )

    # 4) Rename columns: data to item, raw_data to raw_item
    op.alter_column("events", "data", new_column_name="item")
    op.alter_column("events", "raw_data", new_column_name="raw_item")

    # 5) CHECK constraint rebuild (raw_data → raw_item)
    op.drop_constraint("raw_data_invariant", "events", type_="check")
    sdk_values = ", ".join(f"'{v}'" for v in sorted(_SDK_ORIGIN))
    azents_values = ", ".join(f"'{v}'" for v in sorted(_AZ_ORIGIN))
    op.create_check_constraint(
        "raw_item_invariant",
        "events",
        f"(type::text IN ({sdk_values}) AND raw_item IS NOT NULL) "
        f"OR (type::text IN ({azents_values}) AND raw_item IS NULL)",
    )

    # 6) Add source_model column
    op.add_column("events", sa.Column("source_model", sa.Text(), nullable=True))


def downgrade() -> None:
    """Mechanical reverse of upgrade; legacy events rows are not restored.

    In production, data loss makes this downgrade not meaningfully usable.
    It only maintains chain integrity in Test/CI environments, such as the
    testcontainers alembic downgrade base.
    """
    # 6) Drop source_model column
    op.drop_column("events", "source_model")

    # 5) CHECK constraint reverse rebuild (raw_item → raw_data)
    op.drop_constraint("raw_item_invariant", "events", type_="check")

    # 4) Reverse column renames: item to data, raw_item to raw_data
    op.alter_column("events", "raw_item", new_column_name="raw_data")
    op.alter_column("events", "item", new_column_name="data")

    sdk_values = ", ".join(f"'{v}'" for v in sorted(_SDK_ORIGIN))
    azents_values = ", ".join(f"'{v}'" for v in sorted(_AZ_ORIGIN))
    op.create_check_constraint(
        "raw_data_invariant",
        "events",
        f"(type::text IN ({sdk_values}) AND raw_data IS NOT NULL) "
        f"OR (type::text IN ({azents_values}) AND raw_data IS NULL)",
    )

    # 3) events → events_v2 reverse RENAME
    op.execute(
        "ALTER INDEX uq_events_session_external RENAME TO uq_events_v2_session_external"
    )
    op.execute(
        "ALTER INDEX ix_events_session_created RENAME TO ix_events_v2_session_created"
    )
    op.execute("ALTER INDEX ix_events_session_id RENAME TO ix_events_v2_session_id")
    op.rename_table("events", "events_v2")

    # 2) Recreate message_role ENUM
    message_role_enum = postgresql.ENUM(
        *_LEGACY_MESSAGE_ROLE_VALUES,
        name="message_role",
    )
    message_role_enum.create(op.get_bind(), checkfirst=False)

    # 1) Recreate the legacy events table as empty
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                *_LEGACY_MESSAGE_ROLE_VALUES,
                name="message_role",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tool_call_id", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("raw_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["conversation_sessions.id"],
            name="fk_events_session_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_session_id", "events", ["session_id"], unique=False)
