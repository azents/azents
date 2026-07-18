"""add subagent model policy settings

Revision ID: d54f4767b88e
Revises: a8ee43314ef5
Create Date: 2026-07-17 15:41:26.870478

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d54f4767b88e"
down_revision: str | Sequence[str] | None = "a8ee43314ef5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Materialize complete subagent policy settings in existing JSONB values."""
    op.execute(
        sa.text(
            r"""
            CREATE OR REPLACE FUNCTION pg_temp.settings_with_subagent_policy(
                settings_value jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT CASE
                    WHEN settings_value IS NULL THEN NULL
                    WHEN jsonb_typeof(settings_value) != 'object'
                    THEN settings_value
                    ELSE jsonb_set(
                        jsonb_set(
                            settings_value,
                            '{subagent_enabled}',
                            'true'::jsonb,
                            true
                        ),
                        '{subagent_guidance}',
                        'null'::jsonb,
                        true
                    )
                END
            $$;

            CREATE OR REPLACE FUNCTION pg_temp.option_with_subagent_policy(
                option_value jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT CASE
                    WHEN jsonb_typeof(option_value) != 'object'
                    THEN option_value
                    ELSE jsonb_set(
                        option_value,
                        '{settings}',
                        pg_temp.settings_with_subagent_policy(
                            CASE
                                WHEN jsonb_typeof(option_value->'settings') = 'object'
                                THEN option_value->'settings'
                                ELSE '{}'::jsonb
                            END
                        ),
                        true
                    )
                END
            $$;

            CREATE OR REPLACE FUNCTION pg_temp.options_with_subagent_policy(
                option_values jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT CASE
                    WHEN option_values IS NULL THEN NULL
                    WHEN jsonb_typeof(option_values) != 'array'
                    THEN option_values
                    ELSE COALESCE(
                        (
                            SELECT jsonb_agg(
                                pg_temp.option_with_subagent_policy(option_value)
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

            UPDATE agents
            SET selectable_model_options =
                pg_temp.options_with_subagent_policy(selectable_model_options);

            UPDATE workspace_model_settings
            SET default_selectable_model_options =
                pg_temp.options_with_subagent_policy(
                    default_selectable_model_options
                )
            WHERE default_selectable_model_options IS NOT NULL;

            UPDATE agent_sessions
            SET current_model_settings =
                pg_temp.settings_with_subagent_policy(current_model_settings)
            WHERE current_model_settings IS NOT NULL;
            """
        )
    )


def downgrade() -> None:
    """Refuse downgrade because later subagent policy intent may exist."""
    raise RuntimeError(
        "d54f4767b88e is irreversible because later selectable model settings may "
        "contain explicit subagent policy intent"
    )
