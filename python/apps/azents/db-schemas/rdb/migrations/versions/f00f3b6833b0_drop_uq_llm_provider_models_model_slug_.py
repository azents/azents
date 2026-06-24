"""drop_uq_llm_provider_models_model_slug_provider

Revision ID: f00f3b6833b0
Revises: 3156f6b811df
Create Date: 2026-02-23 21:39:36.616603

"""

# pyright: reportUnknownArgumentType=false

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f00f3b6833b0"
down_revision: str | Sequence[str] | None = "3156f6b811df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the (model_slug, provider) unique constraint.

    Remove the incorrect unique constraint so multiple model_identifiers can be
    registered for the same provider. The correct uniqueness basis is the
    composite PK (provider, model_identifier).
    """
    op.drop_constraint(
        "uq_llm_provider_models_model_slug_provider",
        "llm_provider_models",
        type_="unique",
    )


def downgrade() -> None:
    """Restore the (model_slug, provider) unique constraint."""
    op.create_unique_constraint(
        "uq_llm_provider_models_model_slug_provider",
        "llm_provider_models",
        ["model_slug", "provider"],
    )
