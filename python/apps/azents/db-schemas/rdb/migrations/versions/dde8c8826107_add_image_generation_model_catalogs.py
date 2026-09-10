"""Add image generation model catalogs."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "dde8c8826107"
down_revision: str | Sequence[str] | None = "6b53a0a15d11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    postgresql.ENUM(
        "conversation",
        "image_generation",
        name="llm_catalog_purpose",
    ).create(bind, checkfirst=True)
    op.add_column(
        "llm_catalogs",
        sa.Column(
            "purpose",
            postgresql.ENUM(name="llm_catalog_purpose", create_type=False),
            nullable=True,
        ),
    )
    op.execute("UPDATE llm_catalogs SET purpose = 'conversation'")
    op.alter_column("llm_catalogs", "purpose", nullable=False)
    op.drop_index(
        "uq_llm_catalogs_integration_target",
        table_name="llm_catalogs",
    )
    op.drop_index(
        "uq_llm_catalogs_system_scope_provider_target",
        table_name="llm_catalogs",
    )
    op.create_index(
        "uq_llm_catalogs_system_scope_provider_target_purpose",
        "llm_catalogs",
        ["provider", "lowerer_target", "purpose"],
        unique=True,
        postgresql_where=sa.text("scope = 'system'"),
    )
    op.create_index(
        "uq_llm_catalogs_integration_target_purpose",
        "llm_catalogs",
        ["provider_integration_id", "lowerer_target", "purpose"],
        unique=True,
        postgresql_where=sa.text("scope = 'integration'"),
    )
    op.add_column(
        "llm_provider_integrations",
        sa.Column(
            "catalog_configuration_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "llm_catalog_snapshots",
        sa.Column("catalog_configuration_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_catalog_sync_attempts",
        sa.Column("catalog_configuration_version", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE llm_catalog_snapshots AS snapshot
        SET catalog_configuration_version = 1
        FROM llm_catalogs AS catalog
        WHERE snapshot.catalog_id = catalog.id
          AND catalog.scope = 'integration'
        """
    )
    op.execute(
        """
        UPDATE llm_catalog_sync_attempts AS attempt
        SET catalog_configuration_version = 1
        FROM llm_catalogs AS catalog
        WHERE attempt.catalog_id = catalog.id
          AND catalog.scope = 'integration'
        """
    )
    op.create_table(
        "image_generation_catalog_entries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("catalog_id", sa.String(length=32), nullable=False),
        sa.Column("snapshot_id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(name="llm_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("provider_model_identifier", sa.String(length=300), nullable=False),
        sa.Column("display_name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommendation_rank", sa.Integer(), nullable=True),
        sa.Column(
            "lifecycle_status",
            postgresql.ENUM(name="llm_model_lifecycle_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "visibility_status",
            postgresql.ENUM(name="llm_catalog_entry_visibility", create_type=False),
            nullable=False,
        ),
        sa.Column("provider_integration_id", sa.String(length=32), nullable=False),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "projection_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("hidden_reason", sa.String(length=160), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["catalog_id"],
            ["llm_catalogs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_integration_id"],
            ["llm_provider_integrations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["llm_catalog_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "provider_model_identifier",
            name="uq_image_generation_catalog_entries_snapshot_model",
        ),
    )
    op.create_index(
        "ix_image_generation_catalog_entries_catalog_rank",
        "image_generation_catalog_entries",
        ["catalog_id", "recommendation_rank", "display_name"],
    )
    op.create_index(
        "ix_image_generation_catalog_entries_snapshot_id",
        "image_generation_catalog_entries",
        ["snapshot_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_image_generation_catalog_entries_snapshot_id",
        table_name="image_generation_catalog_entries",
    )
    op.drop_index(
        "ix_image_generation_catalog_entries_catalog_rank",
        table_name="image_generation_catalog_entries",
    )
    op.drop_table("image_generation_catalog_entries")
    op.execute("DELETE FROM llm_catalogs WHERE purpose = 'image_generation'")
    op.drop_column("llm_catalog_sync_attempts", "catalog_configuration_version")
    op.drop_column("llm_catalog_snapshots", "catalog_configuration_version")
    op.drop_column(
        "llm_provider_integrations",
        "catalog_configuration_version",
    )
    op.drop_index(
        "uq_llm_catalogs_integration_target_purpose",
        table_name="llm_catalogs",
    )
    op.drop_index(
        "uq_llm_catalogs_system_scope_provider_target_purpose",
        table_name="llm_catalogs",
    )
    op.create_index(
        "uq_llm_catalogs_system_scope_provider_target",
        "llm_catalogs",
        ["provider", "lowerer_target"],
        unique=True,
        postgresql_where=sa.text("scope = 'system'"),
    )
    op.create_index(
        "uq_llm_catalogs_integration_target",
        "llm_catalogs",
        ["provider_integration_id", "lowerer_target"],
        unique=True,
        postgresql_where=sa.text("scope = 'integration'"),
    )
    op.drop_column("llm_catalogs", "purpose")
    postgresql.ENUM(name="llm_catalog_purpose").drop(op.get_bind(), checkfirst=True)
