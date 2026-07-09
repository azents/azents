"""repair workspace selectable model options

Revision ID: e5f4b33f401e
Revises: bbdfefd7ddf2
Create Date: 2026-07-09 19:37:58.149717

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f4b33f401e"
down_revision: str | Sequence[str] | None = "bbdfefd7ddf2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Repair selectable options created with a null lightweight selection."""
    op.execute(
        """
        UPDATE workspace_model_settings
        SET
            default_lightweight_model_selection = COALESCE(
                NULLIF(default_lightweight_model_selection, 'null'::jsonb),
                default_model_selection
            ),
            default_selectable_model_options = CASE
                WHEN default_model_selection IS NULL THEN NULL
                WHEN COALESCE(
                    NULLIF(default_lightweight_model_selection, 'null'::jsonb),
                    default_model_selection
                ) = default_model_selection THEN
                    jsonb_build_array(
                        jsonb_build_object(
                            'label', 'default',
                            'model_selection', default_model_selection
                        )
                    )
                ELSE
                    jsonb_build_array(
                        jsonb_build_object(
                            'label', 'default',
                            'model_selection', default_model_selection
                        ),
                        jsonb_build_object(
                            'label', 'lightweight',
                            'model_selection', default_lightweight_model_selection
                        )
                    )
            END,
            default_main_model_label = CASE
                WHEN default_model_selection IS NULL THEN NULL
                ELSE 'default'
            END,
            default_lightweight_model_label = CASE
                WHEN default_model_selection IS NULL THEN NULL
                WHEN COALESCE(
                    NULLIF(default_lightweight_model_selection, 'null'::jsonb),
                    default_model_selection
                ) = default_model_selection THEN 'default'
                ELSE 'lightweight'
            END
        WHERE
            jsonb_typeof(default_selectable_model_options) = 'array'
            AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements(default_selectable_model_options) AS option
                WHERE option->'model_selection' IS NULL
                   OR option->'model_selection' = 'null'::jsonb
            )
        """
    )


def downgrade() -> None:
    """Keep repaired data when downgrading."""
