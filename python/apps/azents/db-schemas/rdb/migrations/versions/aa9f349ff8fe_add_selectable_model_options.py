"""add selectable model options

Revision ID: aa9f349ff8fe
Revises: 5bf8f3df1f0a
Create Date: 2026-07-09 13:35:12.257414

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "aa9f349ff8fe"
down_revision: str | Sequence[str] | None = "5bf8f3df1f0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agents",
        sa.Column(
            "selectable_model_options",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column("main_model_label", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("lightweight_model_label", sa.String(length=80), nullable=True),
    )
    op.execute(
        """
        UPDATE agents
        SET
            selectable_model_options = CASE
                WHEN model_selection = lightweight_model_selection THEN
                    jsonb_build_array(
                        jsonb_build_object(
                            'label', 'default',
                            'model_selection', model_selection
                        )
                    )
                ELSE
                    jsonb_build_array(
                        jsonb_build_object(
                            'label', 'default',
                            'model_selection', model_selection
                        ),
                        jsonb_build_object(
                            'label', 'lightweight',
                            'model_selection', lightweight_model_selection
                        )
                    )
            END,
            main_model_label = 'default',
            lightweight_model_label = CASE
                WHEN model_selection = lightweight_model_selection
                THEN 'default'
                ELSE 'lightweight'
            END
        """
    )
    op.alter_column("agents", "selectable_model_options", nullable=False)
    op.alter_column("agents", "main_model_label", nullable=False)
    op.alter_column("agents", "lightweight_model_label", nullable=False)
    op.create_check_constraint(
        "ck_agents_selectable_model_options_shape",
        "agents",
        "jsonb_typeof(selectable_model_options) = 'array' "
        "AND jsonb_array_length(selectable_model_options) BETWEEN 1 AND 10",
    )

    op.add_column(
        "workspace_model_settings",
        sa.Column(
            "default_selectable_model_options",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "workspace_model_settings",
        sa.Column("default_main_model_label", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "workspace_model_settings",
        sa.Column(
            "default_lightweight_model_label", sa.String(length=80), nullable=True
        ),
    )
    op.execute(
        """
        UPDATE workspace_model_settings
        SET
            default_lightweight_model_selection = COALESCE(
                default_lightweight_model_selection,
                default_model_selection
            ),
            default_selectable_model_options = CASE
                WHEN default_model_selection IS NULL THEN NULL
                WHEN COALESCE(
                    default_lightweight_model_selection,
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
                    default_lightweight_model_selection,
                    default_model_selection
                ) = default_model_selection THEN 'default'
                ELSE 'lightweight'
            END
        """
    )
    op.create_check_constraint(
        "ck_workspace_model_settings_default_selectable_model_options_shape",
        "workspace_model_settings",
        "default_selectable_model_options IS NULL OR "
        "(jsonb_typeof(default_selectable_model_options) = 'array' "
        "AND jsonb_array_length(default_selectable_model_options) BETWEEN 1 AND 10)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_workspace_model_settings_default_selectable_model_options_shape",
        "workspace_model_settings",
        type_="check",
    )
    op.drop_column("workspace_model_settings", "default_lightweight_model_label")
    op.drop_column("workspace_model_settings", "default_main_model_label")
    op.drop_column("workspace_model_settings", "default_selectable_model_options")

    op.drop_constraint(
        "ck_agents_selectable_model_options_shape",
        "agents",
        type_="check",
    )
    op.drop_column("agents", "lightweight_model_label")
    op.drop_column("agents", "main_model_label")
    op.drop_column("agents", "selectable_model_options")
