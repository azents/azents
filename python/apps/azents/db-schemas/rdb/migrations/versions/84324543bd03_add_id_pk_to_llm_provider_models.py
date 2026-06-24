"""add_id_pk_to_llm_provider_models

Revision ID: 84324543bd03
Revises: f00f3b6833b0
Create Date: 2026-02-23 22:00:00.000000

"""

# pyright: reportUnknownArgumentType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "84324543bd03"
down_revision: str | Sequence[str] | None = "f00f3b6833b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add an id PK to the llm_provider_models table.

    0. Drop the agents FK constraint, which is required before dropping the PK
    1. Add the id column as nullable
    2. Fill existing rows with gen_random_uuid(), with no data loss
    3. Add a NOT NULL constraint
    4. Drop the existing composite PK (provider, model_identifier)
    5. Set id as the new PK
    6. Add the (provider, model_identifier) unique constraint
    7. Recreate the agents FK against the unique constraint
    """
    # 0. Drop the agents FK constraint to remove dependency before dropping the PK
    op.drop_constraint(
        "fk_agents_llm_provider_model",
        "agents",
        type_="foreignkey",
    )

    # 1. Add the id column as nullable
    op.add_column(
        "llm_provider_models",
        sa.Column("id", sa.String(32), nullable=True),
    )

    # 2. Fill existing rows with UUIDs as 32-character hex without hyphens
    op.execute(
        "UPDATE llm_provider_models SET id = replace(gen_random_uuid()::text, '-', '')"
    )

    # 3. Add NOT NULL constraint
    op.alter_column("llm_provider_models", "id", nullable=False)

    # 4. Drop existing composite PK constraint
    op.drop_constraint(
        "llm_provider_models_pkey",
        "llm_provider_models",
        type_="primary",
    )

    # 5. Set id as the new PK
    op.create_primary_key(
        "llm_provider_models_pkey",
        "llm_provider_models",
        ["id"],
    )

    # 6. Add (provider, model_identifier) unique constraint
    op.create_unique_constraint(
        "uq_llm_provider_models_provider_model_identifier",
        "llm_provider_models",
        ["provider", "model_identifier"],
    )

    # 7. Recreate agents FK against the unique constraint
    op.create_foreign_key(
        "fk_agents_llm_provider_model",
        "agents",
        "llm_provider_models",
        ["llm_provider_model_provider", "llm_provider_model_identifier"],
        ["provider", "model_identifier"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Remove the id PK and restore the (provider, model_identifier) composite PK."""
    # 0. Drop agents FK
    op.drop_constraint(
        "fk_agents_llm_provider_model",
        "agents",
        type_="foreignkey",
    )

    # Drop unique constraint
    op.drop_constraint(
        "uq_llm_provider_models_provider_model_identifier",
        "llm_provider_models",
        type_="unique",
    )

    # Drop id PK
    op.drop_constraint(
        "llm_provider_models_pkey",
        "llm_provider_models",
        type_="primary",
    )

    # Restore composite PK
    op.create_primary_key(
        "llm_provider_models_pkey",
        "llm_provider_models",
        ["provider", "model_identifier"],
    )

    # Drop id column
    op.drop_column("llm_provider_models", "id")

    # Recreate agents FK against the composite PK
    op.create_foreign_key(
        "fk_agents_llm_provider_model",
        "agents",
        "llm_provider_models",
        ["llm_provider_model_provider", "llm_provider_model_identifier"],
        ["provider", "model_identifier"],
        ondelete="RESTRICT",
    )
