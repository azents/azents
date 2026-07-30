"""Discard unrecoverable legacy External Channel state."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4d6ed822762c"
down_revision: str | Sequence[str] | None = "cb091fe69575"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Terminalize and discard legacy state that cannot cross the cutover."""
    op.execute(
        sa.text(
            """
            LOCK TABLE
                external_channel_events,
                external_channel_pending_contexts,
                external_channel_resources,
                external_channel_bindings,
                external_channel_conversation_admissions,
                external_channel_access_requests,
                external_channel_resource_provisionings,
                external_channel_invocation_batches,
                external_channel_works
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE external_channel_works AS work
            SET status = 'finished',
                finished_at = COALESCE(work.finished_at, now()),
                state_revision = work.state_revision + 1,
                desired_progress_payload = NULL,
                desired_progress_revision = work.desired_progress_revision + 1,
                updated_at = now()
            FROM external_channel_bindings AS binding
            JOIN external_channel_resources AS resource
              ON resource.id = binding.resource_id
            WHERE work.binding_id = binding.id
              AND work.status = 'active'
              AND binding.status = 'active'
              AND (
                    binding.activation_status IN ('waiting_hydration', 'wake_pending')
                 OR NOT EXISTS (
                        SELECT 1
                        FROM external_channel_invocation_batches AS batch
                        WHERE batch.binding_id = binding.id
                    )
                 OR NOT EXISTS (
                        SELECT 1
                        FROM agent_sessions AS session
                        WHERE session.id = binding.agent_session_id
                    )
                 OR NOT EXISTS (
                        SELECT 1
                        FROM external_channel_agent_routes AS route
                        WHERE route.id = binding.route_id
                    )
                 OR NOT (
                        (
                            resource.provider_resource_key LIKE 'slack:%'
                            AND array_length(
                                string_to_array(resource.provider_resource_key, ':'),
                                1
                            ) = 4
                        )
                        OR (
                            resource.provider_resource_key LIKE 'discord:%'
                            AND array_length(
                                string_to_array(resource.provider_resource_key, ':'),
                                1
                            ) = 3
                            AND COALESCE(
                                NULLIF(resource.labels ->> 'delivery_channel_id', ''),
                                NULLIF(resource.labels ->> 'thread_channel_id', ''),
                                NULLIF(resource.labels ->> 'thread_id', '')
                            ) IS NOT NULL
                        )
                    )
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE external_channel_bindings AS binding
            SET status = 'disconnected',
                disconnected_at = COALESCE(binding.disconnected_at, now()),
                disconnect_reason = 'cutover_unrecoverable_state',
                updated_at = now()
            FROM external_channel_resources AS resource
            WHERE resource.id = binding.resource_id
              AND binding.status = 'active'
              AND (
                    binding.activation_status IN ('waiting_hydration', 'wake_pending')
                 OR NOT EXISTS (
                        SELECT 1
                        FROM external_channel_invocation_batches AS batch
                        WHERE batch.binding_id = binding.id
                    )
                 OR NOT EXISTS (
                        SELECT 1
                        FROM agent_sessions AS session
                        WHERE session.id = binding.agent_session_id
                    )
                 OR NOT EXISTS (
                        SELECT 1
                        FROM external_channel_agent_routes AS route
                        WHERE route.id = binding.route_id
                    )
                 OR NOT (
                        (
                            resource.provider_resource_key LIKE 'slack:%'
                            AND array_length(
                                string_to_array(resource.provider_resource_key, ':'),
                                1
                            ) = 4
                        )
                        OR (
                            resource.provider_resource_key LIKE 'discord:%'
                            AND array_length(
                                string_to_array(resource.provider_resource_key, ':'),
                                1
                            ) = 3
                            AND COALESCE(
                                NULLIF(resource.labels ->> 'delivery_channel_id', ''),
                                NULLIF(resource.labels ->> 'thread_channel_id', ''),
                                NULLIF(resource.labels ->> 'thread_id', '')
                            ) IS NOT NULL
                        )
                    )
              )
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE external_channel_resources
            SET hydration_status = 'bounded',
                updated_at = now()
            WHERE hydration_status IN ('pending', 'running', 'incomplete')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE external_channel_conversation_admissions
            SET status = 'expired',
                updated_at = now()
            WHERE status IN ('pending_selection', 'selected', 'awaiting_access')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE external_channel_access_requests
            SET status = 'expired',
                decision_summary = 'Discarded during External Channel cutover.',
                decided_at = now(),
                updated_at = now()
            WHERE status = 'pending'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE external_channel_resource_provisionings
            SET status = 'failed',
                error_kind = 'cutover_discarded',
                error_summary = 'Discarded during External Channel cutover.',
                attempted_at = COALESCE(attempted_at, now()),
                completed_at = now(),
                updated_at = now()
            WHERE status IN ('pending', 'attempting')
            """
        )
    )
    op.execute(sa.text("DELETE FROM external_channel_pending_contexts"))
    op.execute(sa.text("DELETE FROM external_channel_events"))


def downgrade() -> None:
    """Leave discarded legacy state terminal."""
