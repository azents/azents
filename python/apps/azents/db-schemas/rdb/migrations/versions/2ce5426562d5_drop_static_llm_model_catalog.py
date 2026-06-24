"""drop static llm model catalog"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2ce5426562d5"
down_revision: str | Sequence[str] | None = "38703f9ea36e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove static LLM model catalog tables and enums."""
    op.drop_table("llm_model_overrides", if_exists=True)
    op.drop_table("llm_provider_models", if_exists=True)
    op.drop_table("llm_models", if_exists=True)
    op.drop_table("llm_catalog_sources", if_exists=True)
    op.execute("DROP TYPE IF EXISTS llm_model_lifecycle_status")
    op.execute("DROP TYPE IF EXISTS llm_catalog_source_status")
    op.execute("DROP TYPE IF EXISTS llm_catalog_source_type")
    op.execute("DROP TYPE IF EXISTS llm_model_developer")


def _create_enum_if_missing(name: str, values: list[str]) -> None:
    """Create the PostgreSQL enum type if it is missing."""
    allowed_names = {
        "llm_model_developer",
        "llm_model_lifecycle_status",
        "llm_catalog_source_type",
        "llm_catalog_source_status",
    }
    if name not in allowed_names:
        raise ValueError("Unexpected enum type name.")
    quoted_values = ", ".join(f"'{value}'" for value in values)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{name}') THEN
                CREATE TYPE {name} AS ENUM ({quoted_values});
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    """Recreate static LLM model catalog tables and enums."""
    _create_enum_if_missing(
        "llm_model_developer",
        ["openai", "anthropic", "google", "meta", "mistral"],
    )
    _create_enum_if_missing(
        "llm_model_lifecycle_status",
        ["active", "deprecated", "removed_from_source", "local_only", "disabled"],
    )
    _create_enum_if_missing(
        "llm_catalog_source_type",
        ["external_catalog", "provider_adapter", "local_override"],
    )
    _create_enum_if_missing(
        "llm_catalog_source_status",
        ["unknown", "active", "failed", "disabled"],
    )
    llm_model_developer = postgresql.ENUM(
        name="llm_model_developer",
        create_type=False,
    )
    llm_model_lifecycle_status = postgresql.ENUM(
        name="llm_model_lifecycle_status",
        create_type=False,
    )
    llm_catalog_source_type = postgresql.ENUM(
        name="llm_catalog_source_type",
        create_type=False,
    )
    llm_catalog_source_status = postgresql.ENUM(
        name="llm_catalog_source_status",
        create_type=False,
    )

    op.create_table(
        "llm_catalog_sources",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("type", llm_catalog_source_type, nullable=False),
        sa.Column("status", llm_catalog_source_status, nullable=False),
        sa.Column("version", sa.String(length=255), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "raw_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        "ix_llm_catalog_sources_status",
        "llm_catalog_sources",
        ["status"],
    )
    op.create_index(
        "ix_llm_catalog_sources_last_success_at",
        "llm_catalog_sources",
        ["last_success_at"],
    )

    op.create_table(
        "llm_models",
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("model_developer", llm_model_developer, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_key", sa.String(length=255), nullable=True),
        sa.Column("source_model_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_key"],
            ["llm_catalog_sources.key"],
            name="fk_llm_models_source_key_llm_catalog_sources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("slug"),
    )
    op.create_index("ix_llm_models_source_key", "llm_models", ["source_key"])

    op.create_table(
        "llm_provider_models",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(name="llm_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("model_identifier", sa.String(length=255), nullable=False),
        sa.Column("model_slug", sa.String(length=255), nullable=False),
        sa.Column(
            "capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("thinking", sa.Boolean(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("lifecycle_status", llm_model_lifecycle_status, nullable=False),
        sa.Column(
            "raw_source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("source_key", sa.String(length=255), nullable=True),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_slug"], ["llm_models.slug"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_key"],
            ["llm_catalog_sources.key"],
            name="fk_llm_provider_models_source_key_llm_catalog_sources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "model_identifier",
            name="uq_llm_provider_models_provider_model_identifier",
        ),
    )
    op.create_index(
        "ix_llm_provider_models_source_key",
        "llm_provider_models",
        ["source_key"],
    )
    op.create_index(
        "ix_llm_provider_models_lifecycle_status",
        "llm_provider_models",
        ["lifecycle_status"],
    )
    op.create_index(
        "ix_llm_provider_models_last_synced_at",
        "llm_provider_models",
        ["last_synced_at"],
    )

    op.create_table(
        "llm_model_overrides",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(name="llm_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("model_identifier", sa.String(length=255), nullable=False),
        sa.Column("override", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "model_identifier",
            name="uq_llm_model_overrides_provider_model_identifier",
        ),
    )
    op.create_index(
        "ix_llm_model_overrides_expires_at",
        "llm_model_overrides",
        ["expires_at"],
    )
