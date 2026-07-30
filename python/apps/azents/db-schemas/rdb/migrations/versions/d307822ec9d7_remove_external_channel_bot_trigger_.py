"""remove external channel bot trigger policy

Revision ID: d307822ec9d7
Revises: f1a13c6dc46d
Create Date: 2026-07-30 07:42:46.288036

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d307822ec9d7"
down_revision: str | Sequence[str] | None = "f1a13c6dc46d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "external_channel_agent_route_bot_policy_archive",
        sa.Column("route_id", sa.String(length=32), nullable=False),
        sa.Column("allow_bot_messages", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["external_channel_agent_routes.id"],
            name="external_channel_agent_route_bot_policy_archive_route_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "route_id",
            name="external_channel_agent_route_bot_policy_archive_pkey",
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO external_channel_agent_route_bot_policy_archive (
                route_id,
                allow_bot_messages
            )
            SELECT id, allow_bot_messages
            FROM external_channel_agent_routes
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH pending_sources AS (
                SELECT source_message_id
                FROM external_channel_access_requests
                WHERE status = 'pending'
                UNION
                SELECT source_message_id
                FROM external_channel_conversation_admissions
                WHERE status IN (
                    'pending_selection',
                    'selected',
                    'awaiting_access'
                )
            ),
            scrub_targets AS (
                SELECT messages.id
                FROM external_channel_messages AS messages
                JOIN pending_sources
                  ON pending_sources.source_message_id = messages.id
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM external_channel_message_revisions AS revisions
                    JOIN external_channel_invocation_batch_items AS batch_items
                      ON batch_items.message_revision_id = revisions.id
                    WHERE revisions.message_id = messages.id
                )
            )
            UPDATE external_channel_messages AS messages
            SET current_revision_id = NULL,
                original_url = NULL,
                pending_size = 0
            FROM scrub_targets
            WHERE messages.id = scrub_targets.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH pending_sources AS (
                SELECT source_message_id
                FROM external_channel_access_requests
                WHERE status = 'pending'
                UNION
                SELECT source_message_id
                FROM external_channel_conversation_admissions
                WHERE status IN (
                    'pending_selection',
                    'selected',
                    'awaiting_access'
                )
            )
            DELETE FROM external_channel_message_revisions AS revisions
            USING pending_sources
            WHERE revisions.message_id = pending_sources.source_message_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM external_channel_invocation_batch_items AS batch_items
                  WHERE batch_items.message_revision_id = revisions.id
              )
            """
        )
    )
    op.drop_column("external_channel_agent_routes", "allow_bot_messages")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "external_channel_agent_routes",
        sa.Column(
            "allow_bot_messages",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE external_channel_agent_routes AS routes
            SET allow_bot_messages = archive.allow_bot_messages
            FROM external_channel_agent_route_bot_policy_archive AS archive
            WHERE archive.route_id = routes.id
            """
        )
    )
    op.drop_table("external_channel_agent_route_bot_policy_archive")
