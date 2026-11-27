"""add agent vault requests

Revision ID: 44439b9001d3
Revises: 5feaf00415cd
Create Date: 2026-11-27 20:16:55.554775

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "44439b9001d3"
down_revision: str | Sequence[str] | None = "5feaf00415cd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = postgresql.ENUM(
    "open", "submitted", "expired", name="vault_request_status", create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE event_kind ADD VALUE 'vault_request'")
    op.execute("ALTER TYPE event_kind ADD VALUE 'vault_request_completed'")
    op.execute("ALTER TYPE mailbox_item_kind ADD VALUE 'vault_request_completed'")
    _STATUS.create(op.get_bind())
    op.create_table(
        "agent_vault_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(32),
            sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("anchor_event_id", sa.String(32), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False),
        sa.Column("creation_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("destination", postgresql.JSONB(), nullable=True),
        sa.Column("status", _STATUS, server_default="open", nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("post_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("receipt", postgresql.JSONB(), nullable=True),
        sa.Column("edit_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "anchor_event_id", name="uq_agent_vault_requests_anchor_event_id"
        ),
        sa.CheckConstraint(
            "(status = 'open') = (terminal_at IS NULL)",
            name="ck_agent_vault_requests_terminal",
        ),
    )
    op.create_index(
        "ix_agent_vault_requests_session_id", "agent_vault_requests", ["session_id"]
    )
    op.create_index(
        "ix_agent_vault_requests_open_deadline",
        "agent_vault_requests",
        ["deadline_at", "id"],
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_agent_vault_requests_unclaimed_create",
        "agent_vault_requests",
        ["creation_at", "id"],
        postgresql_where=sa.text(
            "status = 'open' AND destination IS NOT NULL AND post_claimed_at IS NULL"
        ),
    )
    op.create_index(
        "ix_agent_vault_requests_unclaimed_edit",
        "agent_vault_requests",
        ["terminal_at", "id"],
        postgresql_where=sa.text(
            "terminal_at IS NOT NULL AND receipt IS NOT NULL "
            "AND edit_claimed_at IS NULL"
        ),
    )


def downgrade() -> None:
    """Keep retained request and completion authority intact."""
    raise RuntimeError("Agent Vault request migration is irreversible.")
