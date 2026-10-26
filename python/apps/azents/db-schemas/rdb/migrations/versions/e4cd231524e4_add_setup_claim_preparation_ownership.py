"""Add setup claim preparation ownership."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4cd231524e4"
down_revision: str | Sequence[str] | None = "5074c3290716"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "external_channel_setup_claims"
_STATUS = postgresql.ENUM(
    "pending",
    "running",
    "dispatching",
    name="external_channel_setup_preparation_status",
    create_type=False,
)


def upgrade() -> None:
    """Add inactive-by-default preparation state to existing claims."""
    _STATUS.create(op.get_bind(), checkfirst=True)
    for column in (
        sa.Column("preparation_status", _STATUS, nullable=True),
        sa.Column("preparation_configuration_generation", sa.Integer(), nullable=True),
        sa.Column(
            "preparation_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "preparation_next_attempt_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("preparation_lease_owner", sa.String(32), nullable=True),
        sa.Column("preparation_lease_until", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column(_TABLE, column)
    op.create_index(
        "ix_external_channel_setup_claims_preparation_due",
        _TABLE,
        ["preparation_status", "preparation_next_attempt_at"],
    )


def downgrade() -> None:
    """Require active preparation to drain before removing its durable state."""
    active = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM external_channel_setup_claims "
            "WHERE preparation_status IS NOT NULL"
        )
    )
    if active:
        raise RuntimeError("Active setup preparation must drain before downgrade.")
    op.drop_index("ix_external_channel_setup_claims_preparation_due", table_name=_TABLE)
    for name in (
        "preparation_lease_until",
        "preparation_lease_owner",
        "preparation_next_attempt_at",
        "preparation_attempt_count",
        "preparation_configuration_generation",
        "preparation_status",
    ):
        op.drop_column(_TABLE, name)
    _STATUS.drop(op.get_bind(), checkfirst=True)
