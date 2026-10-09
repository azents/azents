"""Add unpublished GitHub user creation attempts."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e89fba791b40"
down_revision: str | Sequence[str] | None = "8c432dfdd6c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep desired configuration and reviewed candidates outside Toolkit lists."""
    op.create_table(
        "github_user_oauth_creations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("session_id", sa.String(32), nullable=False),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("encrypted_setup", sa.Text(), nullable=False),
        sa.Column("encrypted_candidate", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "exchanging",
                "review",
                name="github_user_attempt_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_github_user_oauth_creations_subject",
        "github_user_oauth_creations",
        ["session_id", "workspace_id", "agent_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    """Require local cancellation of known candidates before dropping their table."""
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM github_user_oauth_creations "
            "WHERE encrypted_candidate IS NOT NULL)"
        )
    ):
        raise RuntimeError(
            "Cancel local GitHub user creation candidates before schema downgrade."
        )
    op.drop_table("github_user_oauth_creations")
