"""remove workspace team concept

Revision ID: c57516043fac
Revises: 4dc75aa48547
Create Date: 2026-06-22 07:56:24.606270

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c57516043fac"
down_revision: str | Sequence[str] | None = "4dc75aa48547"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DELETE FROM toolkit_scopes WHERE scope_type = 'team'")
    op.drop_index("ix_team_members_workspace_user_id", table_name="team_members")
    op.drop_index("ix_team_members_team_id", table_name="team_members")
    op.drop_table("team_members")
    op.drop_index("ix_teams_parent_team_id", table_name="teams")
    op.drop_index("ix_teams_workspace_id", table_name="teams")
    op.drop_table("teams")
    op.execute("DROP TYPE team_member_role")
    op.execute("ALTER TYPE toolkit_scope_type RENAME TO toolkit_scope_type_old")
    op.execute("CREATE TYPE toolkit_scope_type AS ENUM ('workspace')")
    op.execute(
        "ALTER TABLE toolkit_scopes "
        "ALTER COLUMN scope_type TYPE toolkit_scope_type "
        "USING scope_type::text::toolkit_scope_type"
    )
    op.execute("DROP TYPE toolkit_scope_type_old")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TYPE toolkit_scope_type RENAME TO toolkit_scope_type_old")
    op.execute("CREATE TYPE toolkit_scope_type AS ENUM ('team', 'workspace')")
    op.execute(
        "ALTER TABLE toolkit_scopes "
        "ALTER COLUMN scope_type TYPE toolkit_scope_type "
        "USING scope_type::text::toolkit_scope_type"
    )
    op.execute("DROP TYPE toolkit_scope_type_old")

    team_member_role = postgresql.ENUM(
        "owner", "manager", "member", name="team_member_role", create_type=False
    )
    team_member_role.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "teams",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("parent_team_id", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("depth >= 1 AND depth <= 3", name="chk_teams_depth"),
        sa.ForeignKeyConstraint(["parent_team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_teams_workspace_slug"),
    )
    op.create_index("ix_teams_workspace_id", "teams", ["workspace_id"])
    op.create_index("ix_teams_parent_team_id", "teams", ["parent_team_id"])
    op.create_table(
        "team_members",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("team_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_user_id", sa.String(length=32), nullable=False),
        sa.Column("role", team_member_role, nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_user_id"], ["workspace_users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "team_id",
            "workspace_user_id",
            name="uq_team_members_team_workspace_user",
        ),
    )
    op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
    op.create_index(
        "ix_team_members_workspace_user_id", "team_members", ["workspace_user_id"]
    )
