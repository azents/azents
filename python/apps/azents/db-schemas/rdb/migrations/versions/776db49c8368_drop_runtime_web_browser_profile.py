"""drop runtime web browser profile

Revision ID: 776db49c8368
Revises: 9fa04ea90acb
Create Date: 2026-09-13 15:21:35.349755

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "776db49c8368"
down_revision: str | Sequence[str] | None = "9fa04ea90acb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove browser-specific identity state."""
    op.drop_column("runtime_web_gateway_identities", "browser_profile")


def downgrade() -> None:
    """Restore the retired browser profile for rollback compatibility."""
    op.add_column(
        "runtime_web_gateway_identities",
        sa.Column(
            "browser_profile",
            sa.String(length=120),
            nullable=False,
            server_default="chromium-152",
        ),
    )
    op.alter_column(
        "runtime_web_gateway_identities",
        "browser_profile",
        server_default=None,
    )
