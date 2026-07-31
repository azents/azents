"""Terminalize fully promoted legacy External Channel wakes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "699b38c35430"
down_revision: str | Sequence[str] | None = "d307822ec9d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Terminalize only undispatched wakes whose mailbox promotion is proven."""
    op.execute(
        sa.text(
            """
            UPDATE external_channel_invocation_batches AS batch
            SET wake_dispatch_status = 'dispatched',
                wake_dispatch_claimed_at = NULL
            FROM external_channel_bindings AS binding,
                 external_channel_conversation_positions AS position
            WHERE batch.wake_dispatch_status IN ('pending', 'claimed')
              AND batch.mailbox_item_id IS NULL
              AND binding.id = batch.binding_id
              AND position.connection_id = batch.connection_id
              AND position.id = batch.conversation_position_id
              AND position.read_through_position >= batch.trigger_position
              AND EXISTS (
                    SELECT 1
                    FROM external_channel_invocation_batch_items AS item
                    WHERE item.batch_id = batch.id
              )
              AND NOT EXISTS (
                    SELECT 1
                    FROM mailbox_items AS mailbox
                    WHERE mailbox.session_id = binding.agent_session_id
                      AND mailbox.kind::text = 'external_channel_invocation'
                      AND mailbox.idempotency_key =
                          'external-channel-invocation:' || batch.id
              )
              AND NOT EXISTS (
                    SELECT 1
                    FROM external_channel_invocation_batch_items AS item
                    JOIN external_channel_message_revisions AS revision
                      ON revision.id = item.message_revision_id
                    JOIN external_channel_messages AS message
                      ON message.id = revision.message_id
                    WHERE item.batch_id = batch.id
                      AND NOT EXISTS (
                            SELECT 1
                            FROM events AS event
                            WHERE event.session_id = binding.agent_session_id
                              AND event.kind::text =
                                  'external_channel_message'
                              AND event.payload->>'binding_id' =
                                  batch.binding_id
                              AND event.payload->>'invocation_batch_id' =
                                  batch.id
                              AND event.payload->>'external_message_id' =
                                  message.id
                              AND event.payload->>'revision_id' =
                                  revision.id
                      )
              )
            """
        )
    )


def downgrade() -> None:
    """Leave proven promoted wakes terminal."""
