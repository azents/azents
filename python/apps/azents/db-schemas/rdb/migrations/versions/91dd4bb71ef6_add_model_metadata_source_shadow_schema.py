"""Add model metadata source shadow schema."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "91dd4bb71ef6"
down_revision: str | Sequence[str] | None = "4550a9c9083a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add inert replacement source and projection provenance state."""
    op.create_table(
        "model_metadata_sources",
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("current_snapshot_id", sa.String(length=32), nullable=True),
        sa.Column("latest_attempt_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("source_key"),
    )
    op.create_table(
        "model_metadata_source_snapshots",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("source_schema_version", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("producer_name", sa.String(length=80), nullable=False),
        sa.Column("producer_version", sa.String(length=80), nullable=False),
        sa.Column("provider_count", sa.Integer(), nullable=False),
        sa.Column("model_count", sa.Integer(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_key"],
            ["model_metadata_sources.source_key"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_key",
            "source_schema_version",
            "source_hash",
            name="uq_model_metadata_source_snapshots_content",
        ),
    )
    op.create_index(
        "ix_model_metadata_source_snapshots_source_created",
        "model_metadata_source_snapshots",
        ["source_key", "created_at"],
        unique=False,
    )
    op.add_column(
        "llm_catalogs",
        sa.Column("rollback_snapshot_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "llm_catalog_snapshots",
        sa.Column(
            "metadata_source_snapshot_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "llm_catalog_snapshots",
        sa.Column(
            "projection_schema_version",
            sa.String(length=20),
            nullable=True,
        ),
    )
    op.add_column(
        "llm_catalog_snapshots",
        sa.Column(
            "runtime_profile_resolver_revision",
            sa.String(length=80),
            nullable=True,
        ),
    )
    op.add_column(
        "llm_catalog_snapshots",
        sa.Column("pydantic_ai_version", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "llm_catalog_snapshots",
        sa.Column("genai_prices_version", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "llm_catalog_snapshots",
        sa.Column("projection_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "llm_catalog_snapshots_metadata_source_snapshot_id_fkey",
        "llm_catalog_snapshots",
        "model_metadata_source_snapshots",
        ["metadata_source_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        "ix_llm_catalog_snapshots_metadata_source_snapshot_id",
        "llm_catalog_snapshots",
        ["metadata_source_snapshot_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove inert replacement source and projection provenance state."""
    op.drop_index(
        "ix_llm_catalog_snapshots_metadata_source_snapshot_id",
        table_name="llm_catalog_snapshots",
    )
    op.drop_constraint(
        "llm_catalog_snapshots_metadata_source_snapshot_id_fkey",
        "llm_catalog_snapshots",
        type_="foreignkey",
    )
    op.drop_column("llm_catalog_snapshots", "projection_fingerprint")
    op.drop_column("llm_catalog_snapshots", "genai_prices_version")
    op.drop_column("llm_catalog_snapshots", "pydantic_ai_version")
    op.drop_column("llm_catalog_snapshots", "runtime_profile_resolver_revision")
    op.drop_column("llm_catalog_snapshots", "projection_schema_version")
    op.drop_column("llm_catalog_snapshots", "metadata_source_snapshot_id")
    op.drop_column("llm_catalogs", "rollback_snapshot_id")
    op.drop_index(
        "ix_model_metadata_source_snapshots_source_created",
        table_name="model_metadata_source_snapshots",
    )
    op.drop_table("model_metadata_source_snapshots")
    op.drop_table("model_metadata_sources")
