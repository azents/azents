"""Add system User roles and bootstrap state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0755571733db"
down_revision: str | Sequence[str] | None = "cf991663b7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

system_user_role = postgresql.ENUM(
    "system_admin",
    name="system_user_role",
)


def upgrade() -> None:
    """Upgrade schema."""
    system_user_role.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "system_user_roles",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "system_admin",
                name="system_user_role",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("granted_by_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "role"),
    )
    op.create_index(
        "ix_system_user_roles_role",
        "system_user_roles",
        ["role"],
        unique=False,
    )
    op.create_index(
        "ix_system_user_roles_granted_by_user_id",
        "system_user_roles",
        ["granted_by_user_id"],
        unique=False,
    )
    op.create_table(
        "system_bootstrap_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "id = 1",
            name="ck_system_bootstrap_states_singleton_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("system_bootstrap_states")
    op.drop_index(
        "ix_system_user_roles_granted_by_user_id",
        table_name="system_user_roles",
    )
    op.drop_index("ix_system_user_roles_role", table_name="system_user_roles")
    op.drop_table("system_user_roles")
    system_user_role.drop(op.get_bind(), checkfirst=False)
