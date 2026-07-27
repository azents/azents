"""Track the capability contract advertised by the current Provider."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1d4e7f2a9b0"
down_revision: str | Sequence[str] | None = "7b4c1d2e9f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add and backfill the current Provider advertisement pointer."""
    op.add_column(
        "runtime_providers",
        sa.Column("current_contract_revision_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE runtime_providers AS provider "
            "SET current_contract_revision_id = COALESCE(("
            "SELECT revision.id FROM runtime_provider_contract_revisions AS revision "
            "WHERE revision.provider_id = provider.id "
            "AND revision.status = 'candidate' "
            "ORDER BY revision.created_at DESC, revision.id DESC LIMIT 1"
            "), provider.accepted_contract_revision_id)"
        )
    )
    op.create_foreign_key(
        "fk_runtime_providers_current_contract_revision_id",
        "runtime_providers",
        "runtime_provider_contract_revisions",
        ["current_contract_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Remove the current Provider advertisement pointer."""
    op.drop_constraint(
        "fk_runtime_providers_current_contract_revision_id",
        "runtime_providers",
        type_="foreignkey",
    )
    op.drop_column("runtime_providers", "current_contract_revision_id")
