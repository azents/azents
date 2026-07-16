# ruff: noqa: E501

"""add model scoped selectable settings

Revision ID: 9d2ed7d656a3
Revises: 7d01fb472aeb
Create Date: 2026-07-16 02:12:54.472384

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9d2ed7d656a3"
down_revision: str | Sequence[str] | None = "7d01fb472aeb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Session settings snapshots and migrate model-scoped JSONB intent."""
    op.add_column(
        "agent_sessions",
        sa.Column(
            "current_model_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.drop_constraint(
        "ck_agent_sessions_current_inference_state",
        "agent_sessions",
        type_="check",
    )

    op.execute(
        sa.text(
            r"""
            CREATE OR REPLACE FUNCTION pg_temp.strip_unsupported_builtin_tools(
                capabilities jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT CASE
                    WHEN capabilities IS NULL THEN NULL
                    ELSE jsonb_set(
                        capabilities,
                        '{built_in_tools}',
                        jsonb_set(
                            COALESCE(capabilities->'built_in_tools', '{}'::jsonb),
                            '{supported}',
                            COALESCE(
                                (
                                    SELECT jsonb_agg(tool_name ORDER BY ordinality)
                                    FROM jsonb_array_elements_text(
                                        CASE
                                            WHEN jsonb_typeof(
                                                capabilities #> '{built_in_tools,supported}'
                                            ) = 'array'
                                            THEN capabilities #> '{built_in_tools,supported}'
                                            ELSE '[]'::jsonb
                                        END
                                    ) WITH ORDINALITY AS tools(tool_name, ordinality)
                                    WHERE tool_name NOT IN (
                                        'web_fetch',
                                        'image_generation'
                                    )
                                ),
                                '[]'::jsonb
                            ),
                            true
                        ),
                        true
                    )
                END
            $$;

            CREATE OR REPLACE FUNCTION pg_temp.strip_selection_tools(
                selection jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT CASE
                    WHEN selection IS NULL THEN NULL
                    ELSE jsonb_set(
                        selection,
                        '{normalized_capabilities}',
                        pg_temp.strip_unsupported_builtin_tools(
                            selection->'normalized_capabilities'
                        ),
                        true
                    )
                END
            $$;

            CREATE OR REPLACE FUNCTION pg_temp.default_selection_tools(
                selection jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT COALESCE(
                    (
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'name', tool_name,
                                'config', '{}'::jsonb
                            )
                            ORDER BY ordinality
                        )
                        FROM jsonb_array_elements_text(
                            CASE
                                WHEN jsonb_typeof(
                                    selection #> '{normalized_capabilities,built_in_tools,supported}'
                                ) = 'array'
                                THEN selection #> '{normalized_capabilities,built_in_tools,supported}'
                                ELSE '[]'::jsonb
                            END
                        ) WITH ORDINALITY AS tools(tool_name, ordinality)
                    ),
                    '[]'::jsonb
                )
            $$;

            CREATE OR REPLACE FUNCTION pg_temp.selection_settings(
                selection jsonb,
                old_parameters jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT jsonb_build_object(
                    'context_window_tokens',
                    COALESCE(old_parameters->'context_window_tokens', 'null'::jsonb),
                    'max_output_tokens',
                    COALESCE(old_parameters->'max_output_tokens', 'null'::jsonb),
                    'builtin_tools',
                    CASE
                        WHEN jsonb_typeof(old_parameters->'builtin_tools') = 'array'
                            AND jsonb_array_length(old_parameters->'builtin_tools') > 0
                        THEN COALESCE(
                            (
                                SELECT jsonb_agg(tool ORDER BY ordinality)
                                FROM jsonb_array_elements(
                                    old_parameters->'builtin_tools'
                                ) WITH ORDINALITY AS tools(tool, ordinality)
                                WHERE EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements_text(
                                        CASE
                                            WHEN jsonb_typeof(
                                                selection #> '{normalized_capabilities,built_in_tools,supported}'
                                            ) = 'array'
                                            THEN selection #> '{normalized_capabilities,built_in_tools,supported}'
                                            ELSE '[]'::jsonb
                                        END
                                    ) AS supported(tool_name)
                                    WHERE tool_name = tool->>'name'
                                )
                            ),
                            '[]'::jsonb
                        )
                        ELSE pg_temp.default_selection_tools(selection)
                    END
                )
            $$;

            CREATE OR REPLACE FUNCTION pg_temp.option_with_settings(
                option_value jsonb,
                old_parameters jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT jsonb_set(
                    jsonb_set(
                        option_value,
                        '{model_selection}',
                        pg_temp.strip_selection_tools(option_value->'model_selection'),
                        true
                    ),
                    '{settings}',
                    pg_temp.selection_settings(
                        pg_temp.strip_selection_tools(option_value->'model_selection'),
                        old_parameters
                    ),
                    true
                )
            $$;
            """
        )
    )

    op.execute(
        sa.text(
            r"""
            UPDATE llm_catalog_entries
            SET normalized_capabilities =
                pg_temp.strip_unsupported_builtin_tools(normalized_capabilities);

            UPDATE agent_sessions AS session
            SET current_model_selection = pg_temp.strip_selection_tools(
                    session.current_model_selection
                ),
                current_model_settings = pg_temp.selection_settings(
                    pg_temp.strip_selection_tools(session.current_model_selection),
                    agent.model_parameters
                )
            FROM agents AS agent
            WHERE session.agent_id = agent.id
              AND session.current_model_selection IS NOT NULL;

            UPDATE agents
            SET model_selection = pg_temp.strip_selection_tools(model_selection),
                lightweight_model_selection = pg_temp.strip_selection_tools(
                    lightweight_model_selection
                ),
                selectable_model_options = (
                    SELECT jsonb_agg(
                        pg_temp.option_with_settings(option_value, agents.model_parameters)
                        ORDER BY ordinality
                    )
                    FROM jsonb_array_elements(selectable_model_options)
                        WITH ORDINALITY AS options(option_value, ordinality)
                );

            UPDATE workspace_model_settings
            SET default_model_selection = pg_temp.strip_selection_tools(
                    default_model_selection
                ),
                default_lightweight_model_selection = pg_temp.strip_selection_tools(
                    default_lightweight_model_selection
                ),
                default_selectable_model_options = CASE
                    WHEN default_selectable_model_options IS NULL THEN NULL
                    ELSE (
                        SELECT jsonb_agg(
                            pg_temp.option_with_settings(option_value, NULL)
                            ORDER BY ordinality
                        )
                        FROM jsonb_array_elements(default_selectable_model_options)
                            WITH ORDINALITY AS options(option_value, ordinality)
                    )
                END;

            UPDATE agents
            SET model_parameters = CASE
                WHEN model_parameters IS NULL THEN NULL
                WHEN model_parameters - ARRAY[
                    'context_window_tokens',
                    'max_output_tokens',
                    'builtin_tools'
                ]::text[] = '{}'::jsonb THEN NULL
                ELSE model_parameters - ARRAY[
                    'context_window_tokens',
                    'max_output_tokens',
                    'builtin_tools'
                ]::text[]
            END;
            """
        )
    )

    op.create_check_constraint(
        "ck_agent_sessions_current_inference_state",
        "agent_sessions",
        "(current_model_target_label IS NULL "
        "AND current_model_selection IS NULL "
        "AND current_model_settings IS NULL "
        "AND current_reasoning_effort IS NULL "
        "AND current_effective_context_window_tokens IS NULL "
        "AND current_effective_auto_compaction_threshold_tokens IS NULL "
        "AND current_inference_resolved_at IS NULL) OR "
        "(current_model_target_label IS NOT NULL "
        "AND current_model_selection IS NOT NULL "
        "AND current_model_settings IS NOT NULL "
        "AND current_effective_context_window_tokens IS NOT NULL "
        "AND current_effective_auto_compaction_threshold_tokens IS NOT NULL "
        "AND current_inference_resolved_at IS NOT NULL)",
    )


def downgrade() -> None:
    """Refuse downgrade because migrated model settings cannot be reconstructed."""
    raise RuntimeError(
        "9d2ed7d656a3 is irreversible because model-scoped settings replaced "
        "Agent-global settings and removed unsupported built-in tool intent"
    )
