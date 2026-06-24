"""refactor to workspace users

Revision ID: 8f9eb22d95aa
Revises: c24a81de3f1a
Create Date: 2026-02-14 13:20:00.000000

"""

# pyright: reportUnknownArgumentType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8f9eb22d95aa"
down_revision: str | Sequence[str] | None = "c24a81de3f1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Move to a WorkspaceUser-centered schema."""
    op.drop_index("ix_team_members_user_id", table_name="team_members")
    op.drop_index("ix_team_members_team_id", table_name="team_members")
    op.drop_table("team_members")

    op.drop_table("users")

    op.create_table(
        "workspace_users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("locale", sa.String(35), nullable=False, server_default="ko-KR"),
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
    )
    op.create_index(
        "ix_workspace_users_workspace_id", "workspace_users", ["workspace_id"]
    )

    role_enum = postgresql.ENUM(name="team_member_role", create_type=False)

    op.create_table(
        "team_members",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "team_id",
            sa.String(32),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_user_id",
            sa.String(32),
            sa.ForeignKey("workspace_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role", role_enum, nullable=False
        ),  # SQLAlchemy Enum column type inference limitation
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
        sa.UniqueConstraint(
            "team_id",
            "workspace_user_id",
            name="uq_team_members_team_workspace_user",
        ),
    )
    op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
    op.create_index(
        "ix_team_members_workspace_user_id",
        "team_members",
        ["workspace_user_id"],
    )


def downgrade() -> None:
    """Revert to the previous User-centered schema."""
    op.drop_index("ix_team_members_workspace_user_id", table_name="team_members")
    op.drop_index("ix_team_members_team_id", table_name="team_members")
    op.drop_table("team_members")

    op.drop_index("ix_workspace_users_workspace_id", table_name="workspace_users")
    op.drop_table("workspace_users")

    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("locale", sa.String(35), nullable=False, server_default="ko-KR"),
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
    )

    role_enum = postgresql.ENUM(name="team_member_role", create_type=False)

    op.create_table(
        "team_members",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "team_id",
            sa.String(32),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role", role_enum, nullable=False
        ),  # SQLAlchemy Enum column type inference limitation
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
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
    )
    op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])
