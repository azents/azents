"""add workspace unique constraint to installations

Add unique constraints that limit each workspace to one Discord installation
and one Slack installation.

Revision ID: 4fbb63d65cda
Revises: 5baa84aabbb7
Create Date: 2026-03-15 12:00:00.000000

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4fbb63d65cda"
down_revision: str | Sequence[str] | None = "5baa84aabbb7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_discord_installations_workspace_id",
        "discord_installations",
        ["workspace_id"],
    )
    op.create_unique_constraint(
        "uq_slack_installations_workspace_id",
        "slack_installations",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_slack_installations_workspace_id",
        "slack_installations",
        type_="unique",
    )
    op.drop_constraint(
        "uq_discord_installations_workspace_id",
        "discord_installations",
        type_="unique",
    )
