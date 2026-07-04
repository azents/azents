"""support mixed workspace defaults

Revision ID: a3abe5d1a632
Revises: dd668956031c
Create Date: 2026-07-04 15:19:35.128189

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3abe5d1a632"
down_revision: str | Sequence[str] | None = "dd668956031c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


agent_project_default_item_type = postgresql.ENUM(
    "existing_project",
    "git_worktree",
    name="agent_project_default_item_type",
)


def upgrade() -> None:
    """Upgrade schema."""
    agent_project_default_item_type.create(op.get_bind(), checkfirst=True)
    op.drop_constraint(
        "uq_agent_project_defaults_agent_path",
        "agent_project_defaults",
        type_="unique",
    )
    op.add_column(
        "agent_project_defaults",
        sa.Column(
            "item_type",
            agent_project_default_item_type,
            nullable=False,
            server_default="existing_project",
        ),
    )
    op.alter_column(
        "agent_project_defaults",
        "item_type",
        server_default=None,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        DELETE FROM agent_project_defaults a
        USING agent_project_defaults b
        WHERE a.agent_id = b.agent_id
          AND a.path = b.path
          AND a.position > b.position
        """
    )
    op.drop_column("agent_project_defaults", "item_type")
    op.create_unique_constraint(
        "uq_agent_project_defaults_agent_path",
        "agent_project_defaults",
        ["agent_id", "path"],
    )
    agent_project_default_item_type.drop(op.get_bind(), checkfirst=True)
