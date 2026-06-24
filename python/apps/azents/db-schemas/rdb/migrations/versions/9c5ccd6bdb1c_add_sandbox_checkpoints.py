"""add sandbox checkpoints

Revision ID: 9c5ccd6bdb1c
Revises: 867f3f7ebc3b
Create Date: 2026-05-07 15:07:28.683138

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9c5ccd6bdb1c"
down_revision: str | Sequence[str] | None = "867f3f7ebc3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add sandbox checkpoint metadata."""
    op.drop_index(
        "ix_agent_runtimes_runtime_state_deadline",
        table_name="agent_runtimes",
    )
    op.execute("ALTER TYPE session_runtime_state RENAME TO session_runtime_state_old")
    op.execute(
        "CREATE TYPE session_runtime_state AS ENUM "
        "('active', 'persisting', 'hibernated', 'restoring', 'expired')"
    )
    op.execute(
        "ALTER TABLE agent_runtimes "
        "ALTER COLUMN runtime_state TYPE session_runtime_state "
        "USING runtime_state::text::session_runtime_state"
    )
    op.execute("DROP TYPE session_runtime_state_old")
    op.create_index(
        "ix_agent_runtimes_runtime_state_deadline",
        "agent_runtimes",
        ["runtime_state", "snapshot_deadline_at"],
        postgresql_where=sa.text("runtime_state = 'active'"),
    )
    op.create_unique_constraint(
        "uq_agent_runtimes_id_workspace_id",
        "agent_runtimes",
        ["id", "workspace_id"],
    )

    sandbox_checkpoint_kind = postgresql.ENUM(
        "hibernate",
        "debounce",
        "manual",
        name="sandbox_checkpoint_kind",
    )
    sandbox_checkpoint_format = postgresql.ENUM(
        "tar_zst",
        name="sandbox_checkpoint_format",
    )

    bind = op.get_bind()
    sandbox_checkpoint_kind.create(bind, checkfirst=True)
    sandbox_checkpoint_format.create(bind, checkfirst=True)

    op.create_table(
        "sandbox_checkpoints",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="sandbox_checkpoint_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "format",
            postgresql.ENUM(name="sandbox_checkpoint_format", create_type=False),
            nullable=False,
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id", "workspace_id"],
            ["agent_runtimes.id", "agent_runtimes.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_sandbox_checkpoints_object_key"),
    )
    op.create_index(
        "ix_sandbox_checkpoints_workspace_id",
        "sandbox_checkpoints",
        ["workspace_id"],
    )
    op.create_index(
        "ix_sandbox_checkpoints_agent_runtime_id_created_at",
        "sandbox_checkpoints",
        ["agent_runtime_id", sa.literal_column("created_at DESC")],
    )
    op.create_index(
        "ix_sandbox_checkpoints_agent_runtime_id_invalidated_at",
        "sandbox_checkpoints",
        ["agent_runtime_id", "invalidated_at"],
    )


def downgrade() -> None:
    """Remove sandbox checkpoint metadata."""
    op.drop_index(
        "ix_sandbox_checkpoints_agent_runtime_id_invalidated_at",
        table_name="sandbox_checkpoints",
    )
    op.drop_index(
        "ix_sandbox_checkpoints_agent_runtime_id_created_at",
        table_name="sandbox_checkpoints",
    )
    op.drop_index(
        "ix_sandbox_checkpoints_workspace_id",
        table_name="sandbox_checkpoints",
    )
    op.drop_table("sandbox_checkpoints")

    bind = op.get_bind()
    postgresql.ENUM(name="sandbox_checkpoint_format").drop(bind, checkfirst=True)
    postgresql.ENUM(name="sandbox_checkpoint_kind").drop(bind, checkfirst=True)

    op.drop_constraint(
        "uq_agent_runtimes_id_workspace_id",
        "agent_runtimes",
        type_="unique",
    )

    op.drop_index(
        "ix_agent_runtimes_runtime_state_deadline",
        table_name="agent_runtimes",
    )
    op.execute(
        "UPDATE agent_runtimes "
        "SET runtime_state = 'active' "
        "WHERE runtime_state IN ('persisting', 'restoring')"
    )
    op.execute("ALTER TYPE session_runtime_state RENAME TO session_runtime_state_old")
    op.execute(
        "CREATE TYPE session_runtime_state AS ENUM ('active', 'hibernated', 'expired')"
    )
    op.execute(
        "ALTER TABLE agent_runtimes "
        "ALTER COLUMN runtime_state TYPE session_runtime_state "
        "USING runtime_state::text::session_runtime_state"
    )
    op.execute("DROP TYPE session_runtime_state_old")
    op.create_index(
        "ix_agent_runtimes_runtime_state_deadline",
        "agent_runtimes",
        ["runtime_state", "snapshot_deadline_at"],
        postgresql_where=sa.text("runtime_state = 'active'"),
    )
