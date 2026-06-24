"""make model catalog scope uniques partial

Revision ID: 2f4e0199c8d1
Revises: a3d35408bb46
Create Date: 2026-06-21 08:45:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2f4e0199c8d1"
down_revision: str | Sequence[str] | None = "a3d35408bb46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(
        "uq_llm_catalogs_system_scope_provider_target",
        "llm_catalogs",
        type_="unique",
    )
    op.drop_constraint(
        "uq_llm_catalogs_integration_target",
        "llm_catalogs",
        type_="unique",
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_llm_catalogs_integration_target",
        table_name="llm_catalogs",
    )
    op.drop_index(
        "uq_llm_catalogs_system_scope_provider_target",
        table_name="llm_catalogs",
    )
    op.create_unique_constraint(
        "uq_llm_catalogs_integration_target",
        "llm_catalogs",
        ["provider_integration_id", "lowerer_target"],
    )
    op.create_unique_constraint(
        "uq_llm_catalogs_system_scope_provider_target",
        "llm_catalogs",
        ["scope", "provider", "lowerer_target"],
    )
