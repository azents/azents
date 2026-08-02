"""advance external channel lifecycle policy v2

Revision ID: b00cf0366fa3
Revises: 7e425e8e3b7b
Create Date: 2026-08-02 18:49:54.310707

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b00cf0366fa3"
down_revision: str | Sequence[str] | None = "7e425e8e3b7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Advance incomplete External Channel purge snapshots to policy version 2."""
    op.execute(
        sa.text(
            """
            UPDATE archived_session_purge_participant_executions AS execution
            SET
                policy_version = 2,
                phase = 'pending',
                attempt_count = 0,
                blocked_by_participant_key = NULL,
                last_error_kind = NULL,
                last_error_summary = NULL,
                operational_summary = NULL,
                prepared_at = NULL,
                cleanup_completed_at = NULL,
                verified_at = NULL,
                last_attempt_at = NULL,
                updated_at = now()
            FROM archived_session_purge_jobs AS job
            WHERE execution.purge_job_id = job.id
              AND execution.participant_key = 'session.external-channel'
              AND execution.policy_version = 1
              AND job.status NOT IN ('completed', 'cancelled')
            """
        )
    )


def downgrade() -> None:
    """Refuse rollback after policy-v2 or title state makes v1 unsafe."""
    unsafe = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT EXISTS (
                SELECT 1
                FROM archived_session_purge_participant_executions
                WHERE participant_key = 'session.external-channel'
                  AND policy_version = 2
            ) OR EXISTS (
                SELECT 1 FROM external_channel_session_title_candidates
            ) OR EXISTS (
                SELECT 1 FROM external_channel_discord_thread_title_projections
            )
            """
            )
        )
        .scalar_one()
    )
    if unsafe:
        raise RuntimeError(
            "Cannot downgrade after External Channel lifecycle policy v2 or "
            "automatic title state is written."
        )
