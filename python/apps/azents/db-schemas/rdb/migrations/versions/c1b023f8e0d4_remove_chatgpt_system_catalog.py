"""remove chatgpt system catalog

Revision ID: c1b023f8e0d4
Revises: 4ac866c17faf
Create Date: 2026-07-14 01:43:03.194116

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1b023f8e0d4"
down_revision: str | Sequence[str] | None = "4ac866c17faf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Move ChatGPT OAuth catalog ownership entirely to integrations."""
    op.execute(
        """
        INSERT INTO llm_catalogs (
            id,
            scope,
            provider,
            lowerer_target,
            provider_integration_id
        )
        SELECT
            md5('chatgpt_oauth_catalog:' || integration.id),
            'integration',
            'chatgpt_oauth',
            'litellm',
            integration.id
        FROM llm_provider_integrations AS integration
        WHERE integration.provider = 'chatgpt_oauth'
          AND NOT EXISTS (
              SELECT 1
              FROM llm_catalogs AS catalog
              WHERE catalog.provider_integration_id = integration.id
                AND catalog.lowerer_target = 'litellm'
          )
        """
    )
    op.execute(
        """
        DELETE FROM llm_catalogs
        WHERE scope = 'system'
          AND provider = 'chatgpt_oauth'
        """
    )


def downgrade() -> None:
    """Restore an empty ChatGPT OAuth system catalog."""
    op.execute(
        """
        INSERT INTO llm_catalogs (
            id,
            scope,
            provider,
            lowerer_target,
            provider_integration_id
        )
        SELECT
            md5('chatgpt_oauth_system_catalog:litellm'),
            'system',
            'chatgpt_oauth',
            'litellm',
            NULL
        WHERE NOT EXISTS (
            SELECT 1
            FROM llm_catalogs
            WHERE scope = 'system'
              AND provider = 'chatgpt_oauth'
              AND lowerer_target = 'litellm'
        )
        """
    )
