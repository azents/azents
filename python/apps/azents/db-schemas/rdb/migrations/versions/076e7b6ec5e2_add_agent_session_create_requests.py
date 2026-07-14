from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "076e7b6ec5e2"
down_revision: str | Sequence[str] | None = "7d01fb472aeb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TYPE chat_write_request_type ADD VALUE IF NOT EXISTS 'input_buffer'"
    )
    op.create_table(
        "agent_session_create_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("client_request_id", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("agent_session_id", sa.String(length=32), nullable=True),
        sa.Column("input_buffer_id", sa.String(length=32), nullable=True),
        sa.Column(
            "input_buffer_snapshot",
            postgresql.JSONB(none_as_null=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(agent_session_id IS NULL AND input_buffer_id IS NULL "
            "AND input_buffer_snapshot IS NULL AND completed_at IS NULL) OR "
            "(agent_session_id IS NOT NULL AND input_buffer_id IS NOT NULL "
            "AND input_buffer_snapshot IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_agent_session_create_requests_completion",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "agent_id",
            "client_request_id",
            name="uq_agent_session_create_requests_user_agent_client_request",
        ),
    )
    op.create_index(
        "ix_agent_session_create_requests_agent_session_id",
        "agent_session_create_requests",
        ["agent_session_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop create requests while retaining the PostgreSQL enum value."""
    op.drop_index(
        "ix_agent_session_create_requests_agent_session_id",
        table_name="agent_session_create_requests",
    )
    op.drop_table("agent_session_create_requests")
