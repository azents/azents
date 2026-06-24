"""add model catalog projection tables

Revision ID: a3d35408bb46
Revises: c7b64368f3a1
Create Date: 2026-06-20 19:48:34.880348

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3d35408bb46"
down_revision: str | Sequence[str] | None = "c7b64368f3a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    _create_enums()
    op.create_table(
        "llm_catalogs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "scope",
            postgresql.ENUM(name="llm_catalog_scope", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "provider",
            postgresql.ENUM(name="llm_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("provider_integration_id", sa.String(length=32), nullable=True),
        sa.Column(
            "lowerer_target",
            postgresql.ENUM(name="llm_catalog_lowerer_target", create_type=False),
            nullable=False,
        ),
        sa.Column("current_snapshot_id", sa.String(length=32), nullable=True),
        sa.Column("latest_attempt_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["provider_integration_id"],
            ["llm_provider_integrations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "provider",
            "lowerer_target",
            name="uq_llm_catalogs_system_scope_provider_target",
        ),
        sa.UniqueConstraint(
            "provider_integration_id",
            "lowerer_target",
            name="uq_llm_catalogs_integration_target",
        ),
    )
    op.create_index(
        "ix_llm_catalogs_provider_integration_id",
        "llm_catalogs",
        ["provider_integration_id"],
    )
    op.create_table(
        "litellm_source_snapshots",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("model_count", sa.Integer(), nullable=False),
        sa.Column("litellm_version", sa.String(length=80), nullable=True),
        sa.Column("loaded_source", sa.String(length=40), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_hash", name="uq_litellm_source_snapshots_source_hash"
        ),
    )
    op.create_table(
        "llm_catalog_snapshots",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("catalog_id", sa.String(length=32), nullable=False),
        sa.Column("source_snapshot_id", sa.String(length=32), nullable=True),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("visible_count", sa.Integer(), nullable=False),
        sa.Column("hidden_count", sa.Integer(), nullable=False),
        sa.Column(
            "diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["catalog_id"], ["llm_catalogs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["litellm_source_snapshots.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_llm_catalog_snapshots_catalog_id",
        "llm_catalog_snapshots",
        ["catalog_id"],
    )
    op.create_table(
        "llm_catalog_entries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("catalog_id", sa.String(length=32), nullable=False),
        sa.Column("snapshot_id", sa.String(length=32), nullable=False),
        sa.Column("provider_integration_id", sa.String(length=32), nullable=True),
        sa.Column(
            "provider",
            postgresql.ENUM(name="llm_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("publisher", sa.String(length=120), nullable=True),
        sa.Column("provider_model_identifier", sa.String(length=300), nullable=False),
        sa.Column(
            "lowerer_target",
            postgresql.ENUM(name="llm_catalog_lowerer_target", create_type=False),
            nullable=False,
        ),
        sa.Column("runtime_model_identifier", sa.String(length=300), nullable=False),
        sa.Column("display_name", sa.String(length=300), nullable=False),
        sa.Column("family", sa.String(length=160), nullable=True),
        sa.Column(
            "normalized_capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
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
            ["catalog_id"], ["llm_catalogs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["llm_catalog_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_llm_catalog_entries_catalog_display",
        "llm_catalog_entries",
        ["catalog_id", "display_name"],
    )
    op.create_index(
        "ix_llm_catalog_entries_catalog_model",
        "llm_catalog_entries",
        ["catalog_id", "provider_model_identifier"],
    )
    op.create_index(
        "ix_llm_catalog_entries_snapshot_id",
        "llm_catalog_entries",
        ["snapshot_id"],
    )
    op.create_table(
        "llm_catalog_sync_attempts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("catalog_id", sa.String(length=32), nullable=True),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="llm_catalog_attempt_status", create_type=False),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("produced_snapshot_id", sa.String(length=32), nullable=True),
        sa.Column("failure_code", sa.String(length=120), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("action_hint", sa.Text(), nullable=True),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("hidden_count", sa.Integer(), nullable=False),
        sa.Column(
            "diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["catalog_id"], ["llm_catalogs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_llm_catalog_sync_attempts_catalog_id",
        "llm_catalog_sync_attempts",
        ["catalog_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_llm_catalog_sync_attempts_catalog_id",
        table_name="llm_catalog_sync_attempts",
    )
    op.drop_table("llm_catalog_sync_attempts")
    op.drop_index(
        "ix_llm_catalog_entries_snapshot_id", table_name="llm_catalog_entries"
    )
    op.drop_index(
        "ix_llm_catalog_entries_catalog_model",
        table_name="llm_catalog_entries",
    )
    op.drop_index(
        "ix_llm_catalog_entries_catalog_display",
        table_name="llm_catalog_entries",
    )
    op.drop_table("llm_catalog_entries")
    op.drop_index(
        "ix_llm_catalog_snapshots_catalog_id",
        table_name="llm_catalog_snapshots",
    )
    op.drop_table("llm_catalog_snapshots")
    op.drop_table("litellm_source_snapshots")
    op.drop_index("ix_llm_catalogs_provider_integration_id", table_name="llm_catalogs")
    op.drop_table("llm_catalogs")
    _drop_enums()


def _create_enums() -> None:
    bind = op.get_bind()
    postgresql.ENUM("system", "integration", name="llm_catalog_scope").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("litellm", name="llm_catalog_lowerer_target").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(
        "running", "succeeded", "failed", name="llm_catalog_attempt_status"
    ).create(bind, checkfirst=True)
    postgresql.ENUM("selectable", "hidden", name="llm_catalog_entry_visibility").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(
        "active",
        "deprecated",
        "removed_from_source",
        "local_only",
        "disabled",
        name="llm_model_lifecycle_status",
    ).create(bind, checkfirst=True)


def _drop_enums() -> None:
    bind = op.get_bind()
    postgresql.ENUM(name="llm_model_lifecycle_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="llm_catalog_entry_visibility").drop(bind, checkfirst=True)
    postgresql.ENUM(name="llm_catalog_attempt_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="llm_catalog_lowerer_target").drop(bind, checkfirst=True)
    postgresql.ENUM(name="llm_catalog_scope").drop(bind, checkfirst=True)
