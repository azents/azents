"""create team members table

Revision ID: c24a81de3f1a
Revises: 2eee6dd31e4b, b3e5a9c71d42
Create Date: 2026-02-13 16:08:00.000000

"""

# pyright: reportUnknownArgumentType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c24a81de3f1a"
down_revision: str | Sequence[str] | None = ("2eee6dd31e4b", "b3e5a9c71d42")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the team_members table."""
    sa.Enum("owner", "manager", "member", name="team_member_role").create(op.get_bind())
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


def downgrade() -> None:
    """Drop the team_members table."""
    op.drop_index("ix_team_members_user_id", table_name="team_members")
    op.drop_index("ix_team_members_team_id", table_name="team_members")
    op.drop_table("team_members")

    sa.Enum(name="team_member_role").drop(op.get_bind())
