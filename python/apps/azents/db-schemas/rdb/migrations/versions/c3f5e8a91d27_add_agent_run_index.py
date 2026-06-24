"""add session scoped agent run index

Revision ID: c3f5e8a91d27
Revises: b9d4a6c13e52
Create Date: 2026-06-02 18:40:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f5e8a91d27"
down_revision: str | Sequence[str] | None = "b9d4a6c13e52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a session-scoped run_index to agent_runs."""
    op.add_column("agent_runs", sa.Column("run_index", sa.Integer(), nullable=True))
    op.execute(
        """
        WITH numbered AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY session_id
                    ORDER BY started_at ASC, id ASC
                ) AS run_index
            FROM agent_runs
        )
        UPDATE agent_runs
        SET run_index = numbered.run_index
        FROM numbered
        WHERE agent_runs.id = numbered.id
        """
    )
    op.alter_column("agent_runs", "run_index", nullable=False)
    op.create_unique_constraint(
        "uq_agent_runs_session_run_index",
        "agent_runs",
        ["session_id", "run_index"],
    )


def downgrade() -> None:
    """Remove the session-scoped run_index from agent_runs."""
    op.drop_constraint(
        "uq_agent_runs_session_run_index",
        "agent_runs",
        type_="unique",
    )
    op.drop_column("agent_runs", "run_index")
