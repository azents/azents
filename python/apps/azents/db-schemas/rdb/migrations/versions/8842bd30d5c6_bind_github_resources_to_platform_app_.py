"""Bind GitHub resources to the Platform App identity.

Revision ID: 8842bd30d5c6
Revises: ec609e0da8ab
Create Date: 2026-07-20 07:47:52.614946

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8842bd30d5c6"
down_revision: str | Sequence[str] | None = "ec609e0da8ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable Platform App identity bindings and partial uniqueness."""
    op.add_column(
        "github_user_installations",
        sa.Column("platform_app_id", sa.String(length=64), nullable=True),
    )
    op.drop_constraint(
        "uq_github_user_installations_user_installation",
        "github_user_installations",
        type_="unique",
    )
    op.create_index(
        "ix_github_user_installations_platform_app_id",
        "github_user_installations",
        ["platform_app_id"],
        unique=False,
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


def downgrade() -> None:
    """Restore the legacy App-agnostic installation uniqueness."""
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
    op.drop_index(
        "ix_github_user_installations_platform_app_id",
        table_name="github_user_installations",
    )
    op.create_unique_constraint(
        "uq_github_user_installations_user_installation",
        "github_user_installations",
        ["user_id", "installation_id"],
    )
    op.drop_column("github_user_installations", "platform_app_id")
