"""rename workspace slug to handle

Revision ID: 2eee6dd31e4b
Revises: a1628b972d3b
Create Date: 2026-02-12 03:49:36.862597

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2eee6dd31e4b"
down_revision: str | Sequence[str] | None = "a1628b972d3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename the slug column in the workspaces table to handle."""
    op.drop_constraint("uq_workspaces_slug", "workspaces", type_="unique")
    op.alter_column("workspaces", "slug", new_column_name="handle")
    op.create_unique_constraint("uq_workspaces_handle", "workspaces", ["handle"])


def downgrade() -> None:
    """Rename the handle column in the workspaces table back to slug."""
    op.drop_constraint("uq_workspaces_handle", "workspaces", type_="unique")
    op.alter_column("workspaces", "handle", new_column_name="slug")
    op.create_unique_constraint("uq_workspaces_slug", "workspaces", ["slug"])
