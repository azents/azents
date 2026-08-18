"""Move xAI catalogs to integrations."""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c044388362c"
down_revision: str | Sequence[str] | None = "30c55c0ef241"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create xAI integration catalogs and remove obsolete system catalogs."""
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
            md5(
                integration.provider::text
                || ':integration_catalog:'
                || integration.id
            ),
            'integration',
            integration.provider,
            'litellm',
            integration.id
        FROM llm_provider_integrations AS integration
        WHERE integration.provider IN ('xai', 'xai_oauth')
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
          AND provider IN ('xai', 'xai_oauth')
        """
    )


def downgrade() -> None:
    """Restore empty xAI system catalogs."""
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
            md5(provider.value || ':system_catalog:litellm'),
            'system',
            provider.value::llm_provider,
            'litellm',
            NULL
        FROM (VALUES ('xai'), ('xai_oauth')) AS provider(value)
        WHERE NOT EXISTS (
            SELECT 1
            FROM llm_catalogs AS catalog
            WHERE catalog.scope = 'system'
              AND catalog.provider = provider.value::llm_provider
              AND catalog.lowerer_target = 'litellm'
        )
        """
    )
