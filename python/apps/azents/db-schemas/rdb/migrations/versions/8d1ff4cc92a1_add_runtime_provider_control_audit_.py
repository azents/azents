"""add runtime provider control audit events

Revision ID: 8d1ff4cc92a1
Revises: 6fe47260f6d5
Create Date: 2026-07-22 14:49:21.153978

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d1ff4cc92a1"
down_revision: str | Sequence[str] | None = "6fe47260f6d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    for value in (
        "enrollment_grant_issued",
        "credential_issued",
        "credential_revoked",
        "connection_opened",
        "connection_closed",
    ):
        op.execute(
            "ALTER TYPE runtime_provider_audit_event_type "
            f"ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    """Downgrade schema."""
    raise RuntimeError(
        "irreversible: runtime_provider_audit_event_type values cannot "
        "be removed safely"
    )
