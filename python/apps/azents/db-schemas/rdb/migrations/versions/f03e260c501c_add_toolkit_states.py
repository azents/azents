"""add toolkit states

Revision ID: f03e260c501c
Revises: ad4b2430dd95
Create Date: 2026-05-17 15:36:20.210424

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

# revision identifiers, used by Alembic.
revision: str = "f03e260c501c"
down_revision: str | Sequence[str] | None = "ad4b2430dd95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    sa.Enum("session", "agent_runtime", name="toolkit_state_scope").create(
        op.get_bind()
    )
    op.create_table(
        "toolkit_states",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "scope",
            postgresql.ENUM(
                "session",
                "agent_runtime",
                name="toolkit_state_scope",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=True),
        sa.Column("toolkit_namespace", sa.String(length=100), nullable=False),
        sa.Column("state_name", sa.String(length=100), nullable=False),
        sa.Column(
            "state_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(scope = 'session' AND session_id IS NOT NULL) OR "
            "(scope = 'agent_runtime' AND session_id IS NULL)",
            name="ck_toolkit_states_scope_session_id",
        ),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"], ["agent_runtimes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "agent_runtime_id",
            "session_id",
            "toolkit_namespace",
            "state_name",
            name="uq_toolkit_states_identity",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_toolkit_states_agent_runtime_id",
        "toolkit_states",
        ["agent_runtime_id"],
        unique=False,
    )
    op.create_index(
        "ix_toolkit_states_session_id", "toolkit_states", ["session_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_toolkit_states_session_id", table_name="toolkit_states")
    op.drop_index("ix_toolkit_states_agent_runtime_id", table_name="toolkit_states")
    op.drop_table("toolkit_states")
    sa.Enum("session", "agent_runtime", name="toolkit_state_scope").drop(op.get_bind())
