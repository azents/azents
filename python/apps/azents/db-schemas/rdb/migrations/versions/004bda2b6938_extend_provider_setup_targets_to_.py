"""extend provider setup targets to personal ownership

Revision ID: 004bda2b6938
Revises: 716e7468e1f5
Create Date: 2026-10-17 08:40:14.853607

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004bda2b6938"
down_revision: str | Sequence[str] | None = "716e7468e1f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM google_oauth_attempts t "
            "LEFT JOIN agents a ON a.id = t.agent_id "
            "WHERE t.workspace_id IS NULL OR (t.agent_id IS NOT NULL "
            "AND (a.id IS NULL OR a.workspace_id <> t.workspace_id))"
        )
    ):
        raise RuntimeError(
            "Inconsistent Provider setup ownership requires explicit repair"
        )
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM github_user_oauth_creations t "
            "LEFT JOIN agents a ON a.id = t.agent_id "
            "WHERE t.workspace_id IS NULL OR (t.agent_id IS NOT NULL "
            "AND (a.id IS NULL OR a.workspace_id <> t.workspace_id))"
        )
    ):
        raise RuntimeError(
            "Inconsistent Provider setup ownership requires explicit repair"
        )
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM github_user_oauth_attempts t "
            "JOIN toolkit_configs c ON c.id = t.toolkit_id "
            "WHERE c.owner_kind = 'user' OR t.workspace_id <> c.workspace_id "
            "OR t.agent_id IS DISTINCT FROM c.owner_agent_id"
        )
    ):
        raise RuntimeError(
            "Inconsistent Provider setup ownership requires explicit repair"
        )
    op.alter_column("google_oauth_attempts", "workspace_id", nullable=True)
    owner_kind = postgresql.ENUM(
        "workspace", "agent", "user", name="toolkit_owner_kind", create_type=False
    )
    op.add_column(
        "google_oauth_attempts", sa.Column("owner_kind", owner_kind, nullable=True)
    )
    op.add_column(
        "google_oauth_attempts",
        sa.Column("owner_user_id", sa.String(32), nullable=True),
    )
    op.get_bind().execute(
        sa.text(
            "UPDATE google_oauth_attempts SET owner_kind = CASE "
            "WHEN agent_id IS NULL THEN 'workspace'::toolkit_owner_kind "
            "ELSE 'agent'::toolkit_owner_kind END"
        )
    )
    op.alter_column("google_oauth_attempts", "owner_kind", nullable=False)
    op.create_foreign_key(
        "fk_google_attempts_owner_user",
        "google_oauth_attempts",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_google_oauth_attempts_owner_user",
        "google_oauth_attempts",
        ["owner_user_id"],
    )
    op.create_check_constraint(
        "ck_google_oauth_attempts_owner_shape",
        "google_oauth_attempts",
        "(owner_kind = 'workspace' AND workspace_id IS NOT NULL "
        "AND agent_id IS NULL AND owner_user_id IS NULL) OR "
        "(owner_kind = 'agent' AND workspace_id IS NOT NULL "
        "AND agent_id IS NOT NULL AND owner_user_id IS NULL) OR "
        "(owner_kind = 'user' AND workspace_id IS NULL AND agent_id IS NULL "
        "AND owner_user_id IS NOT NULL AND owner_user_id = user_id)",
    )
    op.alter_column("github_user_oauth_attempts", "workspace_id", nullable=True)
    op.add_column(
        "github_user_oauth_attempts", sa.Column("owner_kind", owner_kind, nullable=True)
    )
    op.add_column(
        "github_user_oauth_attempts",
        sa.Column("owner_user_id", sa.String(32), nullable=True),
    )
    op.get_bind().execute(
        sa.text(
            "UPDATE github_user_oauth_attempts SET owner_kind = CASE "
            "WHEN agent_id IS NULL THEN 'workspace'::toolkit_owner_kind "
            "ELSE 'agent'::toolkit_owner_kind END"
        )
    )
    op.alter_column("github_user_oauth_attempts", "owner_kind", nullable=False)
    op.create_foreign_key(
        "fk_github_user_attempts_personal_owner",
        "github_user_oauth_attempts",
        "toolkit_configs",
        ["toolkit_id", "owner_user_id"],
        ["id", "owner_user_id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_github_user_oauth_attempts_owner_shape",
        "github_user_oauth_attempts",
        "(owner_kind = 'workspace' AND workspace_id IS NOT NULL "
        "AND agent_id IS NULL AND owner_user_id IS NULL) OR "
        "(owner_kind = 'agent' AND workspace_id IS NOT NULL "
        "AND agent_id IS NOT NULL AND owner_user_id IS NULL) OR "
        "(owner_kind = 'user' AND workspace_id IS NULL AND agent_id IS NULL "
        "AND owner_user_id IS NOT NULL AND owner_user_id = user_id)",
    )

    op.alter_column("github_user_oauth_creations", "workspace_id", nullable=True)
    op.add_column(
        "github_user_oauth_creations",
        sa.Column("owner_kind", owner_kind, nullable=True),
    )
    op.add_column(
        "github_user_oauth_creations",
        sa.Column("owner_user_id", sa.String(32), nullable=True),
    )
    op.get_bind().execute(
        sa.text(
            "UPDATE github_user_oauth_creations SET owner_kind = CASE "
            "WHEN agent_id IS NULL THEN 'workspace'::toolkit_owner_kind "
            "ELSE 'agent'::toolkit_owner_kind END"
        )
    )
    op.alter_column("github_user_oauth_creations", "owner_kind", nullable=False)
    op.create_foreign_key(
        "fk_github_user_creations_owner_user",
        "github_user_oauth_creations",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_github_user_oauth_creations_owner_user",
        "github_user_oauth_creations",
        ["owner_user_id"],
    )
    op.create_check_constraint(
        "ck_github_user_oauth_creations_owner_shape",
        "github_user_oauth_creations",
        "(owner_kind = 'workspace' AND workspace_id IS NOT NULL "
        "AND agent_id IS NULL AND owner_user_id IS NULL) OR "
        "(owner_kind = 'agent' AND workspace_id IS NOT NULL "
        "AND agent_id IS NOT NULL AND owner_user_id IS NULL) OR "
        "(owner_kind = 'user' AND workspace_id IS NULL AND agent_id IS NULL "
        "AND owner_user_id IS NOT NULL AND owner_user_id = user_id)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().scalar(
        sa.text(
            "SELECT (SELECT count(*) FROM google_oauth_attempts "
            "WHERE owner_kind = 'user') "
            "+ (SELECT count(*) FROM github_user_oauth_attempts "
            "WHERE owner_kind = 'user') "
            "+ (SELECT count(*) FROM github_user_oauth_creations "
            "WHERE owner_kind = 'user')"
        )
    ):
        raise RuntimeError(
            "Cannot discard personal Provider setup; account for data first"
        )
    op.drop_constraint(
        "ck_github_user_oauth_creations_owner_shape",
        "github_user_oauth_creations",
        type_="check",
    )
    op.drop_index(
        "ix_github_user_oauth_creations_owner_user",
        table_name="github_user_oauth_creations",
    )
    op.drop_constraint(
        "fk_github_user_creations_owner_user",
        "github_user_oauth_creations",
        type_="foreignkey",
    )
    op.drop_column("github_user_oauth_creations", "owner_user_id")
    op.drop_column("github_user_oauth_creations", "owner_kind")
    op.alter_column("github_user_oauth_creations", "workspace_id", nullable=False)
    op.drop_constraint(
        "ck_github_user_oauth_attempts_owner_shape",
        "github_user_oauth_attempts",
        type_="check",
    )
    op.drop_constraint(
        "fk_github_user_attempts_personal_owner",
        "github_user_oauth_attempts",
        type_="foreignkey",
    )
    op.drop_column("github_user_oauth_attempts", "owner_user_id")
    op.drop_column("github_user_oauth_attempts", "owner_kind")
    op.alter_column("github_user_oauth_attempts", "workspace_id", nullable=False)
    op.drop_constraint(
        "ck_google_oauth_attempts_owner_shape", "google_oauth_attempts", type_="check"
    )
    op.drop_index(
        "ix_google_oauth_attempts_owner_user", table_name="google_oauth_attempts"
    )
    op.drop_constraint(
        "fk_google_attempts_owner_user", "google_oauth_attempts", type_="foreignkey"
    )
    op.drop_column("google_oauth_attempts", "owner_user_id")
    op.drop_column("google_oauth_attempts", "owner_kind")
    op.alter_column("google_oauth_attempts", "workspace_id", nullable=False)
