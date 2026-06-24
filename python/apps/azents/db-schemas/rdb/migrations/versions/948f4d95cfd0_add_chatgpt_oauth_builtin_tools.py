"""add chatgpt oauth builtin tools

Revision ID: 948f4d95cfd0
Revises: 8974ac24b005
Create Date: 2026-05-03 02:46:45.306057

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "948f4d95cfd0"
down_revision: str | Sequence[str] | None = "8974ac24b005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add provider-side built-in tool support information to ChatGPT OAuth models."""
    op.execute(
        """
        UPDATE llm_provider_models
        SET metadata = jsonb_set(
            COALESCE(metadata, '{}'::jsonb),
            '{supported_builtin_tools}',
            (
                SELECT jsonb_agg(tool_name ORDER BY tool_name)
                FROM (
                    SELECT jsonb_array_elements_text(
                        COALESCE(metadata->'supported_builtin_tools', '[]'::jsonb)
                    ) AS tool_name
                    UNION
                    SELECT 'web_search'
                    UNION
                    SELECT 'image_generation'
                ) tools
            ),
            true
        )
        WHERE provider = 'chatgpt_oauth'
          AND model_identifier IN ('gpt-5.1-codex', 'gpt-5.1-codex-max')
        """
    )


def downgrade() -> None:
    """Revert provider-side built-in tool support information.

    Applies to ChatGPT OAuth models.
    """
    op.execute(
        """
        UPDATE llm_provider_models
        SET metadata = jsonb_set(
            COALESCE(metadata, '{}'::jsonb),
            '{supported_builtin_tools}',
            (
                SELECT COALESCE(jsonb_agg(tool_name ORDER BY tool_name), '[]'::jsonb)
                FROM jsonb_array_elements_text(
                    COALESCE(metadata->'supported_builtin_tools', '[]'::jsonb)
                ) AS existing(tool_name)
                WHERE tool_name NOT IN ('web_search', 'image_generation')
            ),
            true
        )
        WHERE provider = 'chatgpt_oauth'
          AND model_identifier IN ('gpt-5.1-codex', 'gpt-5.1-codex-max')
        """
    )
