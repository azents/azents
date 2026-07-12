"""make action execution buffer keyed

Revision ID: d0f03808195a
Revises: d95ca85ef1a2
Create Date: 2026-07-12 00:06:00.701347

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "d0f03808195a"
down_revision: str | Sequence[str] | None = "d95ca85ef1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace durable action-event identity with source InputBuffer identity."""
    op.add_column(
        "action_executions",
        sa.Column("action", JSONB(), nullable=True),
    )
    op.execute(
        "UPDATE action_executions AS executions "
        "SET action = events.payload->'action' "
        "FROM events WHERE events.id = executions.action_event_id"
    )
    op.alter_column("action_executions", "action", nullable=False)
    op.drop_constraint(
        "action_executions_action_event_id_fkey",
        "action_executions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_action_executions_action_event_id",
        "action_executions",
        type_="unique",
    )
    op.drop_index(
        "ix_action_executions_session_id_action_event_id",
        table_name="action_executions",
    )
    op.alter_column(
        "action_executions",
        "action_event_id",
        new_column_name="input_buffer_id",
    )
    op.create_unique_constraint(
        "uq_action_executions_input_buffer_id",
        "action_executions",
        ["input_buffer_id"],
    )
    op.create_index(
        "ix_action_executions_session_id_input_buffer_id",
        "action_executions",
        ["session_id", "input_buffer_id"],
    )


def downgrade() -> None:
    """Reject lossy restoration of the removed action-event identity."""
    raise RuntimeError(
        "d0f03808195a is irreversible because buffer-keyed action executions "
        "have no transcript event identity"
    )
