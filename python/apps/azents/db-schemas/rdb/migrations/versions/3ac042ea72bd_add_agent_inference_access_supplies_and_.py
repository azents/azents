"""Add Agent inference access supplies and hash-only tokens."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3ac042ea72bd"
down_revision: str | Sequence[str] | None = "e4cd231524e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Agent-owned credential lifecycle state."""
    op.create_table(
        "llm_access_supplies",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("issuer", sa.String(256), nullable=False),
        sa.Column("current_token_id", sa.String(32), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_id", "subject", name="uq_llm_access_supply_subject"),
    )
    op.create_index(
        "ix_llm_access_supplies_agent_id", "llm_access_supplies", ["agent_id"]
    )
    op.create_table(
        "llm_access_tokens",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "supply_id",
            sa.String(32),
            sa.ForeignKey("llm_access_supplies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("handover_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("digest", name="uq_llm_access_tokens_digest"),
    )
    op.create_index(
        "ix_llm_access_tokens_supply_id", "llm_access_tokens", ["supply_id"]
    )


def downgrade() -> None:
    """Remove only the added inference credential state."""
    op.drop_table("llm_access_tokens")
    op.drop_table("llm_access_supplies")
