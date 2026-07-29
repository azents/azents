"""activate discord file capabilities

Revision ID: cb091fe69575
Revises: 785dfb44ef23
Create Date: 2026-07-29 05:10:54.816416

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cb091fe69575"
down_revision: str | Sequence[str] | None = "785dfb44ef23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Activate complete file-capable snapshots for usable Discord connections."""
    op.execute(
        """
        UPDATE external_channel_connections
        SET capabilities = capabilities || jsonb_build_object(
            'provider', 'discord',
            'transport', 'http',
            'inbound_events', true,
            'thread_history', true,
            'post_messages', true,
            'update_messages', true,
            'delete_messages', true,
            'download_files', true,
            'upload_files', true
        )
        WHERE provider = 'discord'
          AND status IN ('active', 'degraded')
          AND capabilities IS NOT NULL
          AND capabilities ? 'interaction_public_key'
          AND capabilities ? 'message_command_id'
        """
    )


def downgrade() -> None:
    """Remove Discord capability fields introduced by this revision."""
    op.execute(
        """
        UPDATE external_channel_connections
        SET capabilities = capabilities - ARRAY[
            'provider',
            'transport',
            'inbound_events',
            'thread_history',
            'post_messages',
            'update_messages',
            'delete_messages',
            'download_files',
            'upload_files'
        ]
        WHERE provider = 'discord'
          AND capabilities IS NOT NULL
        """
    )
