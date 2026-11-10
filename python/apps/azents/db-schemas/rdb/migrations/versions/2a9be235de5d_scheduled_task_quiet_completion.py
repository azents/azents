"""Persist Scheduled Task permission and historical completion choices."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2a9be235de5d"
down_revision: str | Sequence[str] | None = "7968012d878c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep all pre-existing work report-required."""
    op.add_column(
        "scheduled_tasks",
        sa.Column(
            "allow_silent", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.alter_column("scheduled_tasks", "allow_silent", server_default=None)
    op.execute("""
        UPDATE toolkit_states
        SET state_json = state_json || jsonb_build_object(
            'allow_silent', false,
            'progress_reported', (
                state_json->>'progress_title' IS NOT NULL
                OR COALESCE((state_json->>'tracker_desired_revision')::int, 0) > 0
            )
        )
        WHERE toolkit_namespace = 'scheduled' AND state_name LIKE 'cycle:%'
    """)
    op.execute("""
        UPDATE events
        SET payload = jsonb_build_object(
            'notify', true, 'suppression_reason', null
        ) || payload
        WHERE kind = 'scheduled_task_result'
    """)


def downgrade() -> None:
    """Keep terminal choices readable across rollback and later re-upgrade."""
    op.execute("""
        UPDATE toolkit_states
        SET state_json = state_json - 'allow_silent' - 'progress_reported'
        WHERE toolkit_namespace = 'scheduled' AND state_name LIKE 'cycle:%'
    """)
    op.drop_column("scheduled_tasks", "allow_silent")
