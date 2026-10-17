"""add user toolkit ownership and access policy

Revision ID: 716e7468e1f5
Revises: f79f6654c302
Create Date: 2026-10-17 07:41:29.909870

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "716e7468e1f5"
down_revision: str | Sequence[str] | None = "f79f6654c302"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind()
    inconsistent = connection.scalar(
        sa.text(
            "SELECT count(*) FROM toolkit_configs t "
            "LEFT JOIN agents a ON a.id = t.owner_agent_id "
            "WHERE t.workspace_id IS NULL OR "
            "(t.owner_agent_id IS NOT NULL AND "
            "(a.id IS NULL OR a.workspace_id <> t.workspace_id))"
        )
    )
    if inconsistent:
        raise RuntimeError("Inconsistent Toolkit ownership requires explicit repair")
    mode = postgresql.ENUM(
        "all", "selected", name="personal_toolkit_access_mode", create_type=False
    )
    mode.create(connection)
    owner_kind = postgresql.ENUM(
        "workspace", "agent", "user", name="toolkit_owner_kind", create_type=False
    )
    owner_kind.create(connection)
    op.add_column("toolkit_configs", sa.Column("owner_kind", owner_kind, nullable=True))
    connection.execute(
        sa.text(
            "UPDATE toolkit_configs SET owner_kind = "
            "CASE WHEN owner_agent_id IS NULL THEN 'workspace'::toolkit_owner_kind "
            "ELSE 'agent'::toolkit_owner_kind END"
        )
    )
    op.alter_column("toolkit_configs", "owner_kind", nullable=False)
    op.alter_column("toolkit_configs", "workspace_id", nullable=True)
    op.add_column(
        "toolkit_configs", sa.Column("owner_user_id", sa.String(32), nullable=True)
    )
    op.create_foreign_key(
        "fk_toolkit_configs_owner_user_id",
        "toolkit_configs",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column(
        "toolkit_configs",
        sa.Column("personal_access_mode", mode, nullable=True),
    )
    op.create_check_constraint(
        "ck_toolkit_configs_owner_shape",
        "toolkit_configs",
        "(owner_kind = 'workspace' AND workspace_id IS NOT NULL "
        "AND owner_agent_id IS NULL AND owner_user_id IS NULL "
        "AND personal_access_mode IS NULL) OR "
        "(owner_kind = 'agent' AND workspace_id IS NOT NULL "
        "AND owner_agent_id IS NOT NULL AND owner_user_id IS NULL "
        "AND personal_access_mode IS NULL) OR "
        "(owner_kind = 'user' AND workspace_id IS NULL AND owner_agent_id IS NULL "
        "AND owner_user_id IS NOT NULL AND personal_access_mode IS NOT NULL)",
    )
    op.create_index(
        "ix_toolkit_configs_owner_user_id", "toolkit_configs", ["owner_user_id"]
    )
    op.create_unique_constraint(
        "uq_toolkit_configs_id_owner_user", "toolkit_configs", ["id", "owner_user_id"]
    )
    op.create_table(
        "personal_toolkit_agents",
        sa.Column("toolkit_id", sa.String(32), nullable=False),
        sa.Column("owner_user_id", sa.String(32), nullable=False),
        sa.Column("agent_id", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["toolkit_id", "owner_user_id"],
            ["toolkit_configs.id", "toolkit_configs.owner_user_id"],
            ondelete="CASCADE",
            name="fk_personal_toolkit_agents_owner",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("toolkit_id", "agent_id"),
    )
    op.create_index(
        "ix_personal_toolkit_agents_agent_id", "personal_toolkit_agents", ["agent_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM toolkit_configs WHERE owner_user_id IS NOT NULL")
    ):
        raise RuntimeError(
            "Cannot discard personal Toolkits; back up and account for personal data"
        )
    op.drop_table("personal_toolkit_agents")
    op.drop_constraint(
        "uq_toolkit_configs_id_owner_user", "toolkit_configs", type_="unique"
    )
    op.drop_index("ix_toolkit_configs_owner_user_id", table_name="toolkit_configs")
    op.drop_constraint(
        "ck_toolkit_configs_owner_shape", "toolkit_configs", type_="check"
    )
    op.drop_column("toolkit_configs", "personal_access_mode")
    op.drop_constraint(
        "fk_toolkit_configs_owner_user_id", "toolkit_configs", type_="foreignkey"
    )
    op.drop_column("toolkit_configs", "owner_user_id")
    op.drop_column("toolkit_configs", "owner_kind")
    op.alter_column("toolkit_configs", "workspace_id", nullable=False)
    postgresql.ENUM(name="personal_toolkit_access_mode").drop(op.get_bind())
    postgresql.ENUM(name="toolkit_owner_kind").drop(op.get_bind())
