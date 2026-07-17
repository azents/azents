"""restore provider hosted image generation capabilities

Revision ID: a8ee43314ef5
Revises: 9d2ed7d656a3
Create Date: 2026-07-17 02:00:20.776380

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8ee43314ef5"
down_revision: str | Sequence[str] | None = "9d2ed7d656a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Restore trusted image generation capability snapshots without opting in."""
    op.execute(
        sa.text(
            r"""
            CREATE OR REPLACE FUNCTION pg_temp.add_image_generation_capability(
                capabilities jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT CASE
                    WHEN capabilities IS NULL
                        OR jsonb_typeof(capabilities) = 'null'
                    THEN jsonb_build_object(
                        'built_in_tools',
                        jsonb_build_object(
                            'supported',
                            jsonb_build_array('image_generation')
                        )
                    )
                    WHEN jsonb_typeof(capabilities) != 'object' THEN capabilities
                    WHEN EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(
                            CASE
                                WHEN jsonb_typeof(
                                    capabilities #> '{built_in_tools,supported}'
                                ) = 'array'
                                THEN capabilities #> '{built_in_tools,supported}'
                                ELSE '[]'::jsonb
                            END
                        ) AS tools(tool_name)
                        WHERE tool_name = 'image_generation'
                    ) THEN capabilities
                    ELSE jsonb_set(
                        capabilities,
                        '{built_in_tools}',
                        jsonb_set(
                            CASE
                                WHEN jsonb_typeof(
                                    capabilities->'built_in_tools'
                                ) = 'object'
                                THEN capabilities->'built_in_tools'
                                ELSE '{}'::jsonb
                            END,
                            '{supported}',
                            CASE
                                WHEN jsonb_typeof(
                                    capabilities #> '{built_in_tools,supported}'
                                ) = 'array'
                                THEN capabilities #> '{built_in_tools,supported}'
                                ELSE '[]'::jsonb
                            END || jsonb_build_array('image_generation'),
                            true
                        ),
                        true
                    )
                END
            $$;

            CREATE OR REPLACE FUNCTION pg_temp.supports_image_generation(
                provider_name text,
                model_identifier text
            ) RETURNS boolean
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT provider_name IN ('openai', 'chatgpt_oauth')
                   AND (
                       lower(model_identifier) LIKE 'gpt-5%'
                       OR lower(model_identifier) LIKE 'gpt-4.1%'
                       OR lower(model_identifier) LIKE 'gpt-4o%'
                       OR lower(model_identifier) LIKE 'o3%'
                   )
            $$;

            CREATE OR REPLACE FUNCTION pg_temp.selection_with_image_generation(
                selection jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT CASE
                    WHEN selection IS NULL THEN NULL
                    WHEN jsonb_typeof(selection) != 'object' THEN selection
                    WHEN pg_temp.supports_image_generation(
                        selection->>'provider',
                        selection->>'model_identifier'
                    ) THEN jsonb_set(
                        selection,
                        '{normalized_capabilities}',
                        pg_temp.add_image_generation_capability(
                            selection->'normalized_capabilities'
                        ),
                        true
                    )
                    ELSE selection
                END
            $$;

            CREATE OR REPLACE FUNCTION pg_temp.option_with_image_generation(
                option_value jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT CASE
                    WHEN jsonb_typeof(option_value) = 'object'
                        AND option_value ? 'model_selection'
                    THEN jsonb_set(
                        option_value,
                        '{model_selection}',
                        pg_temp.selection_with_image_generation(
                            option_value->'model_selection'
                        ),
                        true
                    )
                    ELSE option_value
                END
            $$;

            CREATE OR REPLACE FUNCTION pg_temp.options_with_image_generation(
                option_values jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT CASE
                    WHEN option_values IS NULL THEN NULL
                    WHEN jsonb_typeof(option_values) != 'array' THEN option_values
                    ELSE COALESCE(
                        (
                            SELECT jsonb_agg(
                                pg_temp.option_with_image_generation(option_value)
                                ORDER BY ordinality
                            )
                            FROM jsonb_array_elements(option_values)
                                WITH ORDINALITY AS options(
                                    option_value,
                                    ordinality
                                )
                        ),
                        '[]'::jsonb
                    )
                END
            $$;
            """
        )
    )

    op.execute(
        sa.text(
            r"""
            UPDATE llm_catalog_entries
            SET normalized_capabilities =
                pg_temp.add_image_generation_capability(normalized_capabilities)
            WHERE pg_temp.supports_image_generation(
                provider::text,
                provider_model_identifier
            );

            UPDATE agent_sessions
            SET current_model_selection =
                pg_temp.selection_with_image_generation(current_model_selection)
            WHERE current_model_selection IS NOT NULL;

            UPDATE agents
            SET model_selection =
                    pg_temp.selection_with_image_generation(model_selection),
                lightweight_model_selection =
                    pg_temp.selection_with_image_generation(
                        lightweight_model_selection
                    ),
                selectable_model_options =
                    pg_temp.options_with_image_generation(selectable_model_options);

            UPDATE workspace_model_settings
            SET default_model_selection =
                    pg_temp.selection_with_image_generation(
                        default_model_selection
                    ),
                default_lightweight_model_selection =
                    pg_temp.selection_with_image_generation(
                        default_lightweight_model_selection
                    ),
                default_selectable_model_options =
                    pg_temp.options_with_image_generation(
                        default_selectable_model_options
                    );
            """
        )
    )


def downgrade() -> None:
    """Refuse downgrade because enabled image generation intent may exist."""
    raise RuntimeError(
        "a8ee43314ef5 is irreversible because later model settings may select "
        "the restored image_generation capability"
    )
