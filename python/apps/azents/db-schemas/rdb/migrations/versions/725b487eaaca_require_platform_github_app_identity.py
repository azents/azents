"""Require Platform GitHub App identity.

Revision ID: 725b487eaaca
Revises: 38a236695c9e
Create Date: 2026-07-20 15:28:36.819627

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "725b487eaaca"
down_revision: str | Sequence[str] | None = "38a236695c9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Require an App identity for every installation row."""
    op.drop_index(
        "uq_github_user_installations_unbound_user_installation",
        table_name="github_user_installations",
        postgresql_where=sa.text("platform_app_id IS NULL"),
    )
    op.drop_index(
        "uq_github_user_installations_bound_user_app_installation",
        table_name="github_user_installations",
        postgresql_where=sa.text("platform_app_id IS NOT NULL"),
    )
    op.alter_column(
        "github_user_installations",
        "platform_app_id",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_index(
        "uq_github_user_installations_user_app_installation",
        "github_user_installations",
        ["user_id", "platform_app_id", "installation_id"],
        unique=True,
    )


def downgrade() -> None:
    """Restore the retired nullable identity transition schema."""
    op.drop_index(
        "uq_github_user_installations_user_app_installation",
        table_name="github_user_installations",
    )
    op.alter_column(
        "github_user_installations",
        "platform_app_id",
        existing_type=sa.String(length=64),
        nullable=True,
    )
    op.create_index(
        "uq_github_user_installations_bound_user_app_installation",
        "github_user_installations",
        ["user_id", "platform_app_id", "installation_id"],
        unique=True,
        postgresql_where=sa.text("platform_app_id IS NOT NULL"),
    )
    op.create_index(
        "uq_github_user_installations_unbound_user_installation",
        "github_user_installations",
        ["user_id", "installation_id"],
        unique=True,
        postgresql_where=sa.text("platform_app_id IS NULL"),
    )
