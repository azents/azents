"""Add feature-owned Exchange browser upload operations."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9462aab292cc"
down_revision: str | Sequence[str] | None = "841e7188d527"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist exact upload bindings without cascading cleanup owner deletion."""
    state = postgresql.ENUM(
        "pending", "finalized", name="exchange_upload_state", create_type=False
    )
    state.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "exchange_upload_operations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("publication_id", sa.String(32), nullable=False),
        sa.Column("preview_file_id", sa.String(32), nullable=False),
        sa.Column("workspace_id", sa.String(32), nullable=False),
        sa.Column("agent_id", sa.String(32), nullable=False),
        sa.Column("uploader_user_id", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("expected_size", sa.BigInteger(), nullable=False),
        sa.Column("expected_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleanup_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", state, nullable=False),
        sa.Column("finalize_claim_id", sa.String(128), nullable=True),
        sa.Column("finalize_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleanup_claim_id", sa.String(128), nullable=True),
        sa.Column("cleanup_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleanup_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_exchange_upload_operations"),
        sa.UniqueConstraint(
            "publication_id", name="uq_exchange_upload_operations_publication_id"
        ),
        sa.UniqueConstraint(
            "preview_file_id", name="uq_exchange_upload_operations_preview_file_id"
        ),
        sa.CheckConstraint(
            "expected_size >= 0", name="ck_exchange_upload_operations_expected_size"
        ),
        sa.CheckConstraint(
            "expires_at > created_at AND cleanup_after >= expires_at",
            name="ck_exchange_upload_operations_deadlines",
        ),
        sa.CheckConstraint(
            "(finalize_claim_id IS NULL) = (finalize_lease_until IS NULL)",
            name="ck_exchange_upload_operations_finalize_claim",
        ),
        sa.CheckConstraint(
            "(cleanup_claim_id IS NULL) = (cleanup_lease_until IS NULL)",
            name="ck_exchange_upload_operations_cleanup_claim",
        ),
        sa.CheckConstraint(
            "(state = 'finalized') = (finalized_at IS NOT NULL)",
            name="ck_exchange_upload_operations_finalized",
        ),
    )
    op.create_index(
        "ix_exchange_upload_operations_due_cleanup",
        "exchange_upload_operations",
        ["cleanup_after", "cleanup_lease_until", "id"],
        postgresql_where=sa.text("cleanup_completed_at IS NULL"),
    )


def downgrade() -> None:
    """Remove internal upload operations and their enum."""
    op.drop_index(
        "ix_exchange_upload_operations_due_cleanup",
        table_name="exchange_upload_operations",
    )
    op.drop_table("exchange_upload_operations")
    postgresql.ENUM(name="exchange_upload_state").drop(op.get_bind(), checkfirst=True)
