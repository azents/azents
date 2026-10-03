"""Add exact presentation and draft-bound explicit consolidation dispositions."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "66aa52336fc8"
down_revision: str | Sequence[str] | None = "3be144f78dca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "historical_consolidation_units",
        sa.Column("pass_upper_sequence", sa.BigInteger(), nullable=True),
    )
    postgresql.ENUM("CONSIDERED", "OMITTED", name="consolidation_disposition").create(
        op.get_bind()
    )
    for column in ("considered_draft_revision_id", "presented_attempt_id"):
        op.add_column(
            "historical_consolidation_work",
            sa.Column(column, sa.String(32), nullable=True),
        )
    op.add_column(
        "historical_consolidation_work",
        sa.Column(
            "disposition",
            postgresql.ENUM(
                "CONSIDERED",
                "OMITTED",
                name="consolidation_disposition",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "historical_consolidation_work",
        sa.Column("consideration_reason", sa.String(512), nullable=True),
    )
    op.create_table(
        "historical_consolidation_model_dispatches",
        sa.Column("attempt_id", sa.String(32), nullable=False),
        sa.Column("dispatch_id", sa.String(32), nullable=False),
        sa.Column("request_number", sa.Integer(), nullable=False),
        sa.Column("reserved_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("reserved_output_tokens", sa.BigInteger(), nullable=False),
        sa.Column(
            "usage_recorded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("usage_json", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("attempt_id", "dispatch_id"),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["historical_consolidation_attempts.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "attempt_id",
            "request_number",
            name="uq_historical_consolidation_model_dispatches_number",
        ),
        sa.CheckConstraint(
            "request_number >= 1 AND request_number <= 32 AND "
            "reserved_input_tokens >= 0 AND reserved_input_tokens <= 250000 AND "
            "reserved_output_tokens >= 1 AND reserved_output_tokens <= 16000",
            name="ck_historical_consolidation_model_dispatches_budget",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("historical_consolidation_model_dispatches")
    for column in (
        "consideration_reason",
        "disposition",
        "presented_attempt_id",
        "considered_draft_revision_id",
    ):
        op.drop_column("historical_consolidation_work", column)
    postgresql.ENUM(name="consolidation_disposition").drop(op.get_bind())
    op.drop_column("historical_consolidation_units", "pass_upper_sequence")
