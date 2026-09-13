"""normalize legacy session model settings

Revision ID: 9fa04ea90acb
Revises: e767c81c6ed9
Create Date: 2026-09-13 22:24:35.872182

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9fa04ea90acb"
down_revision: str | Sequence[str] | None = "e767c81c6ed9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove option-scoped fields from stored Session model settings."""
    op.execute(
        """
        UPDATE agent_sessions
        SET current_model_settings =
            current_model_settings
            - 'subagent_enabled'
            - 'subagent_guidance'
        WHERE current_model_settings ? 'subagent_enabled'
           OR current_model_settings ? 'subagent_guidance'
        """
    )


def downgrade() -> None:
    """Restore option-scoped fields from each Session's selected Agent option."""
    op.execute(
        """
        UPDATE agent_sessions AS agent_session
        SET current_model_settings =
            agent_session.current_model_settings
            || jsonb_build_object(
                'subagent_enabled',
                    COALESCE(
                        (
                            SELECT option_value->'subagent_enabled'
                            FROM jsonb_array_elements(
                                agent.selectable_model_options
                            ) AS option_value
                            WHERE option_value->>'label' =
                                agent_session.current_model_target_label
                            LIMIT 1
                        ),
                        'true'::jsonb
                    ),
                'subagent_guidance',
                    COALESCE(
                        (
                            SELECT option_value->'subagent_guidance'
                            FROM jsonb_array_elements(
                                agent.selectable_model_options
                            ) AS option_value
                            WHERE option_value->>'label' =
                                agent_session.current_model_target_label
                            LIMIT 1
                        ),
                        'null'::jsonb
                    )
            )
        FROM agents AS agent
        WHERE agent_session.agent_id = agent.id
          AND agent_session.current_model_settings IS NOT NULL
        """
    )
