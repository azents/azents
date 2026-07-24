"""add model file run lineage

Revision ID: 8fae7b9ab00a
Revises: 1ce295000a20
Create Date: 2026-07-24 14:30:29.362650

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8fae7b9ab00a"
down_revision: str | Sequence[str] | None = "1ce295000a20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Bind every ModelFile to its exact deterministic AgentRun."""
    op.add_column(
        "model_files",
        sa.Column("created_run_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE model_files AS model_file
        SET created_run_id = agent_run.id
        FROM agent_runs AS agent_run
        WHERE agent_run.session_id = model_file.session_id
          AND agent_run.run_index = model_file.created_run_index
        """
    )
    op.create_foreign_key(
        "fk_model_files_created_run_id_agent_runs",
        "model_files",
        "agent_runs",
        ["created_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Remove exact ModelFile AgentRun lineage."""
    op.drop_constraint(
        "fk_model_files_created_run_id_agent_runs",
        "model_files",
        type_="foreignkey",
    )
    op.drop_column("model_files", "created_run_id")
