"""remove discord gateway checkpoint state

Revision ID: 785dfb44ef23
Revises: c51a9e8c6815
Create Date: 2026-07-28 12:30:32.764660

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "785dfb44ef23"
down_revision: str | Sequence[str] | None = "c51a9e8c6815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove transport internals no longer exposed by the high-level SDK."""
    op.drop_column(
        "external_channel_ingress_leases",
        "last_handled_dispatch_sequence",
    )
    op.drop_column(
        "external_channel_ingress_leases",
        "checkpoint_session_fingerprint",
    )
    op.drop_column(
        "external_channel_ingress_leases",
        "checkpoint_version",
    )
    op.drop_column(
        "external_channel_ingress_leases",
        "encrypted_checkpoint",
    )


def downgrade() -> None:
    """Restore the former custom Gateway checkpoint columns."""
    op.add_column(
        "external_channel_ingress_leases",
        sa.Column("encrypted_checkpoint", sa.Text(), nullable=True),
    )
    op.add_column(
        "external_channel_ingress_leases",
        sa.Column("checkpoint_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "external_channel_ingress_leases",
        sa.Column(
            "checkpoint_session_fingerprint",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_ingress_leases",
        sa.Column(
            "last_handled_dispatch_sequence",
            sa.BigInteger(),
            nullable=True,
        ),
    )
