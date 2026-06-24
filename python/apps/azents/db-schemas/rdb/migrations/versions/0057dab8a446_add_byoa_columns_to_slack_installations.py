"""add BYOA columns to slack_installations

Adds slack_app_id and encrypted_signing_secret columns for Slack BYOA support,
and converts single workspace_id/slack_team_id unique constraints to
partial unique indexes.

Revision ID: 0057dab8a446
Revises: a4232f31bc4b
Create Date: 2026-04-13 14:50:35.659403

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057dab8a446"
down_revision: str | Sequence[str] | None = "a4232f31bc4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Drop existing unique constraints
    op.drop_constraint(
        "uq_slack_installations_slack_team_id",
        "slack_installations",
        type_="unique",
    )
    op.drop_constraint(
        "uq_slack_installations_workspace_id",
        "slack_installations",
        type_="unique",
    )

    # 2. Add new columns
    op.add_column(
        "slack_installations",
        sa.Column("slack_app_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "slack_installations",
        sa.Column("encrypted_signing_secret", sa.Text(), nullable=True),
    )

    # 3. Partial unique indexes (created directly with op.execute)
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_slack_installations_slack_app_id "
            "ON slack_installations (slack_app_id) "
            "WHERE slack_app_id IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_slack_installations_workspace_agent "
            "ON slack_installations (workspace_id, agent_id) "
            "WHERE mode = 'byoa'"
        )
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_slack_installations_workspace_platform "
            "ON slack_installations (workspace_id) "
            "WHERE mode = 'platform'"
        )
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_slack_installations_team_platform "
            "ON slack_installations (slack_team_id) "
            "WHERE mode = 'platform'"
        )
    )


def downgrade() -> None:
    """Downgrade schema.

    Warning: if BYOA data exists, restoring the existing unique constraints may
    cause duplicate violations. In production, clean up BYOA data before
    downgrading.
    """
    # Drop indexes in reverse order
    op.drop_index(
        "uq_slack_installations_team_platform",
        table_name="slack_installations",
    )
    op.drop_index(
        "uq_slack_installations_workspace_platform",
        table_name="slack_installations",
    )
    op.drop_index(
        "uq_slack_installations_workspace_agent",
        table_name="slack_installations",
    )
    op.drop_index(
        "uq_slack_installations_slack_app_id",
        table_name="slack_installations",
    )

    # Drop columns
    op.drop_column("slack_installations", "encrypted_signing_secret")
    op.drop_column("slack_installations", "slack_app_id")

    # Restore existing unique constraints
    op.create_unique_constraint(
        "uq_slack_installations_slack_team_id",
        "slack_installations",
        ["slack_team_id"],
    )
    op.create_unique_constraint(
        "uq_slack_installations_workspace_id",
        "slack_installations",
        ["workspace_id"],
    )
