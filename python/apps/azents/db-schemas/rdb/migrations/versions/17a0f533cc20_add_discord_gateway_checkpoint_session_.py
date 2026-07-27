"""Add a Discord Gateway checkpoint session fingerprint."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "17a0f533cc20"
down_revision: str | Sequence[str] | None = "f17b4c8d6a21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store the session scope for the Discord Gateway sequence fence."""
    op.add_column(
        "external_channel_ingress_leases",
        sa.Column(
            "checkpoint_session_fingerprint",
            sa.String(length=64),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove the Discord Gateway checkpoint session fingerprint."""
    op.drop_column(
        "external_channel_ingress_leases",
        "checkpoint_session_fingerprint",
    )
