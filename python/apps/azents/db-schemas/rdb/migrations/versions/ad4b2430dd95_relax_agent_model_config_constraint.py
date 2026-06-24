"""relax agent model config constraint

Revision ID: ad4b2430dd95
Revises: d7423b61f226
Create Date: 2026-05-17 08:06:47.346840

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ad4b2430dd95"
down_revision: str | Sequence[str] | None = "d7423b61f226"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(
        "ck_agents_model_not_null_when_role_agent",
        "agents",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agents_model_not_null_when_role_agent",
        "agents",
        "role = 'subagent' OR "
        "(model_config_id IS NOT NULL OR "
        "(llm_provider_model_id IS NOT NULL AND "
        "llm_provider_integration_id IS NOT NULL))",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_agents_model_not_null_when_role_agent",
        "agents",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agents_model_not_null_when_role_agent",
        "agents",
        "role = 'subagent' OR "
        "(llm_provider_model_id IS NOT NULL AND "
        "llm_provider_integration_id IS NOT NULL)",
    )
