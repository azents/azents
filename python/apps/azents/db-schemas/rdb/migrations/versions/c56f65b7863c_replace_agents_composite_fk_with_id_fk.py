"""replace_agents_composite_fk_with_id_fk

Revision ID: c56f65b7863c
Revises: 84324543bd03
Create Date: 2026-02-24 03:20:40.781741

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c56f65b7863c"
down_revision: str | Sequence[str] | None = "84324543bd03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Change the agents table composite FK to an id-based FK.

    1. Add llm_provider_model_id column as nullable
    2. Backfill it by resolving llm_provider_models.id from existing
       provider/identifier values
    3. Add NOT NULL constraint
    4. Drop existing composite FK
    5. Create new id-based FK
    6. Drop existing composite FK columns
    """
    # 1. Add llm_provider_model_id column as nullable
    op.add_column(
        "agents",
        sa.Column("llm_provider_model_id", sa.String(32), nullable=True),
    )

    # 2. Backfill llm_provider_model_id from existing data
    op.execute(
        """
        UPDATE agents
        SET llm_provider_model_id = pm.id
        FROM llm_provider_models pm
        WHERE agents.llm_provider_model_provider = pm.provider
          AND agents.llm_provider_model_identifier = pm.model_identifier
        """
    )

    # 3. Add NOT NULL constraint
    op.alter_column("agents", "llm_provider_model_id", nullable=False)

    # 4. Drop existing composite FK
    op.drop_constraint(
        "fk_agents_llm_provider_model",
        "agents",
        type_="foreignkey",
    )

    # 5. Create new id-based FK
    op.create_foreign_key(
        "fk_agents_llm_provider_model",
        "agents",
        "llm_provider_models",
        ["llm_provider_model_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # 6. Drop existing composite FK columns
    op.drop_column("agents", "llm_provider_model_provider")
    op.drop_column("agents", "llm_provider_model_identifier")


def downgrade() -> None:
    """Restore the id-based FK back to the composite FK."""
    # 1. Restore composite FK columns as nullable
    op.add_column(
        "agents",
        sa.Column(
            "llm_provider_model_provider",
            sa.Enum(
                "openai",
                "anthropic",
                "google_gemini",
                "aws_bedrock",
                "google_vertex_ai",
                name="llm_provider",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column("llm_provider_model_identifier", sa.String(255), nullable=True),
    )

    # 2. Backfill by reverse lookup from llm_provider_models
    op.execute(
        """
        UPDATE agents
        SET llm_provider_model_provider = pm.provider,
            llm_provider_model_identifier = pm.model_identifier
        FROM llm_provider_models pm
        WHERE agents.llm_provider_model_id = pm.id
        """
    )

    # 3. Add NOT NULL constraint
    op.alter_column("agents", "llm_provider_model_provider", nullable=False)
    op.alter_column("agents", "llm_provider_model_identifier", nullable=False)

    # 4. Drop id-based FK
    op.drop_constraint(
        "fk_agents_llm_provider_model",
        "agents",
        type_="foreignkey",
    )

    # 5. Restore composite FK
    op.create_foreign_key(
        "fk_agents_llm_provider_model",
        "agents",
        "llm_provider_models",
        ["llm_provider_model_provider", "llm_provider_model_identifier"],
        ["provider", "model_identifier"],
        ondelete="RESTRICT",
    )

    # 6. Drop llm_provider_model_id column
    op.drop_column("agents", "llm_provider_model_id")
