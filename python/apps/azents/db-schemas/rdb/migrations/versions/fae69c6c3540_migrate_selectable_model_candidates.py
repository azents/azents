"""Migrate selectable model options to ordered candidate chains."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fae69c6c3540"
down_revision: str | Sequence[str] | None = "c05bc1b811fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade selectable model options to the canonical nested shape."""
    postgresql.ENUM(
        "reservation",
        "probe",
        name="model_candidate_claim_kind",
    ).create(op.get_bind())
    op.add_column(
        "agent_runs",
        sa.Column(
            "model_operation_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "primary_model_reservation",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "title_model_operation_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_table(
        "model_candidate_chain_cutovers",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "schema_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "cutover_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "new_format_written_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "id = 1",
            name="ck_model_candidate_chain_cutovers_singleton",
        ),
        sa.CheckConstraint(
            "schema_version = 1",
            name="ck_model_candidate_chain_cutovers_schema_version",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        """
        INSERT INTO model_candidate_chain_cutovers (id, schema_version)
        VALUES (1, 1)
        """
    )
    op.create_table(
        "model_candidate_health",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column(
            "llm_provider_integration_id",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("model_identifier", sa.Text(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "cooldown_until",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "claim_kind",
            postgresql.ENUM(
                "reservation",
                "probe",
                name="model_candidate_claim_kind",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("claim_owner_id", sa.String(length=32), nullable=True),
        sa.Column("claim_token", sa.String(length=32), nullable=True),
        sa.Column(
            "claim_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_model_candidate_health_generation_positive",
        ),
        sa.CheckConstraint(
            "(claim_kind IS NULL AND claim_owner_id IS NULL "
            "AND claim_token IS NULL AND claim_until IS NULL) OR "
            "(claim_kind IS NOT NULL AND claim_owner_id IS NOT NULL "
            "AND claim_token IS NOT NULL AND claim_until IS NOT NULL)",
            name="ck_model_candidate_health_claim_complete",
        ),
        sa.ForeignKeyConstraint(
            ["llm_provider_integration_id"],
            ["llm_provider_integrations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "llm_provider_integration_id",
            "model_identifier",
        ),
    )
    op.create_index(
        "ix_model_candidate_health_cooldown_until",
        "model_candidate_health",
        ["cooldown_until"],
        unique=False,
    )
    op.drop_constraint(
        "ck_agents_selectable_model_options_shape",
        "agents",
        type_="check",
    )
    op.drop_constraint(
        "ck_ws_model_settings_selectable_options_shape",
        "workspace_model_settings",
        type_="check",
    )

    op.execute(
        """
        UPDATE agents
        SET selectable_model_options = (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'label', option_value->'label',
                    'subagent_enabled',
                        COALESCE(
                            option_value->'settings'->'subagent_enabled',
                            'true'::jsonb
                        ),
                    'subagent_guidance',
                        COALESCE(
                            option_value->'settings'->'subagent_guidance',
                            'null'::jsonb
                        ),
                    'candidates',
                        jsonb_build_array(
                            jsonb_build_object(
                                'model_selection', option_value->'model_selection',
                                'settings',
                                    (option_value->'settings')
                                    - 'subagent_enabled'
                                    - 'subagent_guidance'
                            )
                        )
                )
                ORDER BY option_ordinality
            )
            FROM jsonb_array_elements(selectable_model_options)
                WITH ORDINALITY AS options(option_value, option_ordinality)
        )
        """
    )
    op.execute(
        """
        UPDATE workspace_model_settings
        SET default_selectable_model_options = (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'label', option_value->'label',
                    'subagent_enabled',
                        COALESCE(
                            option_value->'settings'->'subagent_enabled',
                            'true'::jsonb
                        ),
                    'subagent_guidance',
                        COALESCE(
                            option_value->'settings'->'subagent_guidance',
                            'null'::jsonb
                        ),
                    'candidates',
                        jsonb_build_array(
                            jsonb_build_object(
                                'model_selection', option_value->'model_selection',
                                'settings',
                                    (option_value->'settings')
                                    - 'subagent_enabled'
                                    - 'subagent_guidance'
                            )
                        )
                )
                ORDER BY option_ordinality
            )
            FROM jsonb_array_elements(default_selectable_model_options)
                WITH ORDINALITY AS options(option_value, option_ordinality)
        )
        WHERE jsonb_typeof(default_selectable_model_options) = 'array'
        """
    )

    op.create_check_constraint(
        "ck_agents_selectable_model_options_shape",
        "agents",
        "jsonb_typeof(selectable_model_options) = 'array' "
        "AND jsonb_array_length(selectable_model_options) BETWEEN 1 AND 10 "
        "AND NOT jsonb_path_exists("
        "selectable_model_options, "
        "'$[*] ? (!exists(@.candidates) || "
        '@.candidates.type() != "array" || '
        "@.candidates.size() < 1 || @.candidates.size() > 5)'"
        ")",
    )
    op.create_check_constraint(
        "ck_ws_model_settings_selectable_options_shape",
        "workspace_model_settings",
        "default_selectable_model_options IS NULL OR "
        "jsonb_typeof(default_selectable_model_options) = 'null' OR "
        "(jsonb_typeof(default_selectable_model_options) = 'array' "
        "AND jsonb_array_length(default_selectable_model_options) BETWEEN 1 AND 10 "
        "AND NOT jsonb_path_exists("
        "default_selectable_model_options, "
        "'$[*] ? (!exists(@.candidates) || "
        '@.candidates.type() != "array" || '
        "@.candidates.size() < 1 || @.candidates.size() > 5)'"
        "))",
    )


def downgrade() -> None:
    """Restore the singular option shape before any fallback candidate is saved."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM model_candidate_chain_cutovers
                WHERE new_format_written_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade after canonical model configuration writes';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM agents,
                    LATERAL jsonb_array_elements(selectable_model_options) option_value
                WHERE jsonb_array_length(option_value->'candidates') <> 1
            ) OR EXISTS (
                SELECT 1
                FROM workspace_model_settings,
                    LATERAL jsonb_array_elements(
                        CASE
                            WHEN jsonb_typeof(default_selectable_model_options)
                                = 'array'
                            THEN default_selectable_model_options
                            ELSE '[]'::jsonb
                        END
                    ) option_value
                WHERE jsonb_array_length(option_value->'candidates') <> 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade after selectable model fallback writes';
            END IF;
        END
        $$;
        """
    )

    op.drop_constraint(
        "ck_agents_selectable_model_options_shape",
        "agents",
        type_="check",
    )
    op.drop_constraint(
        "ck_ws_model_settings_selectable_options_shape",
        "workspace_model_settings",
        type_="check",
    )

    op.execute(
        """
        UPDATE agents
        SET selectable_model_options = (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'label', option_value->'label',
                    'model_selection',
                        option_value->'candidates'->0->'model_selection',
                    'settings',
                        (option_value->'candidates'->0->'settings')
                        || jsonb_build_object(
                            'subagent_enabled',
                                option_value->'subagent_enabled',
                            'subagent_guidance',
                                option_value->'subagent_guidance'
                        )
                )
                ORDER BY option_ordinality
            )
            FROM jsonb_array_elements(selectable_model_options)
                WITH ORDINALITY AS options(option_value, option_ordinality)
        )
        """
    )
    op.execute(
        """
        UPDATE workspace_model_settings
        SET default_selectable_model_options = (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'label', option_value->'label',
                    'model_selection',
                        option_value->'candidates'->0->'model_selection',
                    'settings',
                        (option_value->'candidates'->0->'settings')
                        || jsonb_build_object(
                            'subagent_enabled',
                                option_value->'subagent_enabled',
                            'subagent_guidance',
                                option_value->'subagent_guidance'
                        )
                )
                ORDER BY option_ordinality
            )
            FROM jsonb_array_elements(default_selectable_model_options)
                WITH ORDINALITY AS options(option_value, option_ordinality)
        )
        WHERE jsonb_typeof(default_selectable_model_options) = 'array'
        """
    )

    op.create_check_constraint(
        "ck_agents_selectable_model_options_shape",
        "agents",
        "jsonb_typeof(selectable_model_options) = 'array' "
        "AND jsonb_array_length(selectable_model_options) BETWEEN 1 AND 10",
    )
    op.create_check_constraint(
        "ck_ws_model_settings_selectable_options_shape",
        "workspace_model_settings",
        "default_selectable_model_options IS NULL OR "
        "jsonb_typeof(default_selectable_model_options) = 'null' OR "
        "(jsonb_typeof(default_selectable_model_options) = 'array' "
        "AND jsonb_array_length(default_selectable_model_options) BETWEEN 1 AND 10)",
    )
    op.drop_index(
        "ix_model_candidate_health_cooldown_until",
        table_name="model_candidate_health",
    )
    op.drop_table("model_candidate_health")
    op.drop_table("model_candidate_chain_cutovers")
    op.drop_column("agent_sessions", "title_model_operation_state")
    op.drop_column("agent_sessions", "primary_model_reservation")
    op.drop_column("agent_runs", "model_operation_state")
    postgresql.ENUM(name="model_candidate_claim_kind").drop(
        op.get_bind(),
        checkfirst=True,
    )
