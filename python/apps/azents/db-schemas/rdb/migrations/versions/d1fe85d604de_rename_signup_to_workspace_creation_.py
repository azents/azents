"""rename signup to workspace creation email verifications

Revision ID: d1fe85d604de
Revises: e34887ecbee0
Create Date: 2026-02-16 01:28:03.662849

"""

from typing import Sequence

from alembic import op

revision: str = "d1fe85d604de"
down_revision: str | Sequence[str] | None = "e34887ecbee0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """signup_email_verifications → workspace_creation_email_verifications."""
    op.rename_table(
        "signup_email_verifications", "workspace_creation_email_verifications"
    )


def downgrade() -> None:
    """workspace_creation_email_verifications → signup_email_verifications."""
    op.rename_table(
        "workspace_creation_email_verifications", "signup_email_verifications"
    )
