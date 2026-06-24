"""add llm provider integration tables

Revision ID: 754ff39d34e0
Revises: 0ef57a5814f7
Create Date: 2026-02-21 11:20:17.977780

"""

# pyright: reportUnknownArgumentType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "754ff39d34e0"
down_revision: str | Sequence[str] | None = "0ef57a5814f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create LLM provider integration related tables."""
    # 1. Create ENUM types
    sa.Enum(
        "openai",
        "anthropic",
        "google_gemini",
        "aws_bedrock",
        "google_vertex_ai",
        name="llm_provider",
    ).create(op.get_bind())
    sa.Enum(
        "openai", "anthropic", "google", "meta", "mistral", name="llm_vendor"
    ).create(op.get_bind())

    provider_enum = postgresql.ENUM(name="llm_provider", create_type=False)
    vendor_enum = postgresql.ENUM(name="llm_vendor", create_type=False)

    # 2. Create the llm_models table
    op.create_table(
        "llm_models",
        sa.Column("slug", sa.String(255), primary_key=True),
        sa.Column(
            "vendor",
            vendor_enum,
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
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
    )

    # 3. Create the llm_provider_models table
    op.create_table(
        "llm_provider_models",
        sa.Column(
            "provider",
            provider_enum,
            primary_key=True,
        ),
        sa.Column("model_identifier", sa.String(255), primary_key=True),
        sa.Column(
            "model_slug",
            sa.String(255),
            sa.ForeignKey("llm_models.slug", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("available", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
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
        sa.UniqueConstraint(
            "model_slug",
            "provider",
            name="uq_llm_provider_models_model_slug_provider",
        ),
    )

    # 4. Create the llm_provider_integrations table
    op.create_table(
        "llm_provider_integrations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider",
            provider_enum,
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=False),
        sa.Column("encrypted_credentials", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
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
    )
    op.create_index(
        "ix_llm_provider_integrations_workspace_id",
        "llm_provider_integrations",
        ["workspace_id"],
    )


def downgrade() -> None:
    """Drop LLM provider integration related tables."""
    op.drop_index(
        "ix_llm_provider_integrations_workspace_id",
        table_name="llm_provider_integrations",
    )
    op.drop_table("llm_provider_integrations")
    op.drop_table("llm_provider_models")
    op.drop_table("llm_models")
    sa.Enum(name="llm_vendor").drop(op.get_bind())
    sa.Enum(name="llm_provider").drop(op.get_bind())
