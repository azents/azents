"""add model config foundation

Revision ID: d7423b61f226
Revises: 61faf051f9f3
Create Date: 2026-05-16 17:28:31.679833

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d7423b61f226"
down_revision: str | Sequence[str] | None = "61faf051f9f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


agent_model_config_inherit_mode = postgresql.ENUM(
    "inherit",
    "custom",
    name="agent_model_config_inherit_mode",
)

DEFAULT_CAPABILITIES_SQL = """
jsonb_build_object(
    'context_window', jsonb_build_object(
        'max_input_tokens', 'null'::jsonb,
        'max_output_tokens', 'null'::jsonb
    ),
    'modalities', jsonb_build_object(
        'input', '[]'::jsonb,
        'output', '[]'::jsonb
    ),
    'tool_calling', jsonb_build_object(
        'supported', false,
        'parallel_tool_calls', 'null'::jsonb,
        'strict_json_schema', 'null'::jsonb
    ),
    'reasoning', jsonb_build_object(
        'supported', false,
        'effort_levels', '[]'::jsonb,
        'summaries', 'null'::jsonb
    ),
    'built_in_tools', jsonb_build_object('supported', '[]'::jsonb),
    'compatibility', jsonb_build_object(
        'provider_family', 'null'::jsonb,
        'responses_api', 'null'::jsonb,
        'unsupported_media_policy', 'null'::jsonb
    )
)
"""


def upgrade() -> None:
    """Add the ModelConfig foundation schema and backfill existing Agents."""
    bind = op.get_bind()
    agent_model_config_inherit_mode.create(bind, checkfirst=True)

    op.create_table(
        "model_configs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("llm_provider_integration_id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(name="llm_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("model_identifier", sa.String(length=255), nullable=False),
        sa.Column("model_display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "model_developer",
            postgresql.ENUM(name="llm_model_developer", create_type=False),
            nullable=False,
        ),
        sa.Column("model_family", sa.String(length=255), nullable=True),
        sa.Column(
            "normalized_capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "model_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "default_parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "default_model",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "default_lightweight_model",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["llm_provider_integration_id"],
            ["llm_provider_integrations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "label", name="uq_model_configs_workspace_id_label"
        ),
    )
    op.create_index(
        "ix_model_configs_workspace_id",
        "model_configs",
        ["workspace_id"],
    )
    op.create_index(
        "ix_model_configs_llm_provider_integration_id",
        "model_configs",
        ["llm_provider_integration_id"],
    )
    op.create_index(
        "uq_model_configs_workspace_default_model",
        "model_configs",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("default_model IS TRUE"),
    )
    op.create_index(
        "uq_model_configs_workspace_default_lightweight_model",
        "model_configs",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("default_lightweight_model IS TRUE"),
    )

    op.add_column("agents", sa.Column("model_config_id", sa.String(32), nullable=True))
    op.add_column(
        "agents",
        sa.Column("lightweight_model_config_id", sa.String(32), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column(
            "model_config_inherit_mode",
            postgresql.ENUM(
                "inherit",
                "custom",
                name="agent_model_config_inherit_mode",
                create_type=False,
            ),
            server_default="custom",
            nullable=False,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "model_parameter_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.execute(sa.text(_assert_legacy_agent_provider_matches_integration_sql()))
    op.execute(sa.text(_backfill_model_configs_sql()))
    op.execute(sa.text(_backfill_agents_sql()))
    op.execute(sa.text(_mark_model_config_defaults_sql()))

    op.create_foreign_key(
        "fk_agents_model_config_id_model_configs",
        "agents",
        "model_configs",
        ["model_config_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agents_lightweight_model_config_id_model_configs",
        "agents",
        "model_configs",
        ["lightweight_model_config_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_agents_model_config_id", "agents", ["model_config_id"])
    op.create_index(
        "ix_agents_lightweight_model_config_id",
        "agents",
        ["lightweight_model_config_id"],
    )
    op.create_check_constraint(
        "ck_agents_model_config_role_agent_custom",
        "agents",
        "role != 'agent' OR model_config_inherit_mode = 'custom'",
    )
    op.create_check_constraint(
        "ck_agents_model_config_inherit_null_refs",
        "agents",
        "model_config_inherit_mode != 'inherit' OR "
        "(model_config_id IS NULL AND lightweight_model_config_id IS NULL)",
    )
    op.alter_column("agents", "model_config_inherit_mode", server_default=None)


def downgrade() -> None:
    """Remove the ModelConfig foundation schema."""
    op.drop_constraint(
        "ck_agents_model_config_inherit_null_refs", "agents", type_="check"
    )
    op.drop_constraint(
        "ck_agents_model_config_role_agent_custom", "agents", type_="check"
    )
    op.drop_index("ix_agents_lightweight_model_config_id", table_name="agents")
    op.drop_index("ix_agents_model_config_id", table_name="agents")
    op.drop_constraint(
        "fk_agents_lightweight_model_config_id_model_configs",
        "agents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agents_model_config_id_model_configs", "agents", type_="foreignkey"
    )
    op.drop_column("agents", "model_parameter_overrides")
    op.drop_column("agents", "model_config_inherit_mode")
    op.drop_column("agents", "lightweight_model_config_id")
    op.drop_column("agents", "model_config_id")

    op.drop_index(
        "uq_model_configs_workspace_default_lightweight_model",
        table_name="model_configs",
    )
    op.drop_index(
        "uq_model_configs_workspace_default_model", table_name="model_configs"
    )
    op.drop_index(
        "ix_model_configs_llm_provider_integration_id", table_name="model_configs"
    )
    op.drop_index("ix_model_configs_workspace_id", table_name="model_configs")
    op.drop_table("model_configs")
    agent_model_config_inherit_mode.drop(op.get_bind(), checkfirst=True)


def _backfill_model_configs_sql() -> str:
    """SQL that migrates existing Agent provider/model pairs to ModelConfig."""
    return f"""
WITH main_pairs AS (
    SELECT DISTINCT
        a.workspace_id,
        a.llm_provider_integration_id,
        a.llm_provider_model_id
    FROM agents a
    WHERE a.llm_provider_integration_id IS NOT NULL
      AND a.llm_provider_model_id IS NOT NULL
), lightweight_pairs AS (
    SELECT DISTINCT
        a.workspace_id,
        a.llm_provider_integration_id,
        compact_pm.id AS llm_provider_model_id
    FROM agents a
    JOIN llm_provider_models main_pm ON main_pm.id = a.llm_provider_model_id
    JOIN llm_provider_models compact_pm
      ON compact_pm.provider = main_pm.provider
     AND compact_pm.model_identifier = a.model_parameters ->> 'compaction_model_id'
    WHERE a.llm_provider_integration_id IS NOT NULL
      AND a.llm_provider_model_id IS NOT NULL
      AND jsonb_typeof(a.model_parameters) = 'object'
      AND a.model_parameters ? 'compaction_model_id'
), pairs AS (
    SELECT * FROM main_pairs
    UNION
    SELECT * FROM lightweight_pairs
)
INSERT INTO model_configs (
    id,
    workspace_id,
    label,
    llm_provider_integration_id,
    provider,
    model_identifier,
    model_display_name,
    model_developer,
    model_family,
    normalized_capabilities,
    model_snapshot,
    source_metadata,
    default_parameters,
    default_model,
    default_lightweight_model,
    enabled,
    last_refreshed_at,
    created_at,
    updated_at
)
SELECT
    md5('model_config:' || p.workspace_id || ':' ||
        p.llm_provider_integration_id || ':' || p.llm_provider_model_id),
    p.workspace_id,
    concat(
        'Migrated ',
        left(pm.model_identifier, 160),
        ' ',
        p.llm_provider_integration_id,
        ' ',
        p.llm_provider_model_id
    ),
    p.llm_provider_integration_id,
    pm.provider,
    pm.model_identifier,
    lm.name,
    lm.model_developer,
    lm.slug,
    COALESCE(pm.capabilities, {DEFAULT_CAPABILITIES_SQL}),
    jsonb_build_object(
        'source', 'legacy_static_catalog',
        'llm_provider_model_id', pm.id,
        'llm_model_slug', pm.model_slug,
        'model_identifier', pm.model_identifier,
        'model_display_name', lm.name,
        'available', pm.available,
        'lifecycle_status', pm.lifecycle_status
    ),
    NULLIF(jsonb_strip_nulls(jsonb_build_object(
        'raw_source_metadata', pm.raw_source_metadata,
        'source_key', pm.source_key,
        'source_record_id', pm.source_record_id
    )), '{{}}'::jsonb),
    NULL,
    false,
    false,
    true,
    pm.last_synced_at,
    now(),
    now()
FROM pairs p
JOIN llm_provider_models pm ON pm.id = p.llm_provider_model_id
JOIN llm_provider_integrations lpi
  ON lpi.id = p.llm_provider_integration_id
 AND lpi.provider = pm.provider
JOIN llm_models lm ON lm.slug = pm.model_slug
ON CONFLICT (id) DO NOTHING
"""


def _assert_legacy_agent_provider_matches_integration_sql() -> str:
    """SQL that verifies legacy Agent provider models match integration providers."""
    return """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM agents a
        JOIN llm_provider_models pm ON pm.id = a.llm_provider_model_id
        JOIN llm_provider_integrations lpi ON lpi.id = a.llm_provider_integration_id
        WHERE a.llm_provider_integration_id IS NOT NULL
          AND a.llm_provider_model_id IS NOT NULL
          AND lpi.provider != pm.provider
    ) THEN
        RAISE EXCEPTION
            'legacy agent provider model and integration provider mismatch';
    END IF;
END $$
"""


def _mark_model_config_defaults_sql() -> str:
    """SQL that sets migrated default flags by workspace."""
    return """
WITH main_counts AS (
    SELECT
        a.workspace_id,
        a.model_config_id,
        count(*) AS usage_count
    FROM agents a
    WHERE a.model_config_id IS NOT NULL
    GROUP BY a.workspace_id, a.model_config_id
), ranked_main AS (
    SELECT
        workspace_id,
        model_config_id,
        row_number() OVER (
            PARTITION BY workspace_id
            ORDER BY usage_count DESC, model_config_id ASC
        ) AS rank
    FROM main_counts
), lightweight_counts AS (
    SELECT
        a.workspace_id,
        mc.id AS model_config_id,
        count(*) AS usage_count
    FROM agents a
    JOIN llm_provider_models main_pm ON main_pm.id = a.llm_provider_model_id
    JOIN llm_provider_models compact_pm
      ON compact_pm.provider = main_pm.provider
     AND compact_pm.model_identifier = a.model_parameters ->> 'compaction_model_id'
    JOIN model_configs mc
      ON mc.workspace_id = a.workspace_id
     AND mc.llm_provider_integration_id = a.llm_provider_integration_id
     AND mc.model_identifier = compact_pm.model_identifier
     AND mc.provider = compact_pm.provider
    WHERE jsonb_typeof(a.model_parameters) = 'object'
      AND a.model_parameters ? 'compaction_model_id'
    GROUP BY a.workspace_id, mc.id
), ranked_lightweight AS (
    SELECT
        workspace_id,
        model_config_id,
        row_number() OVER (
            PARTITION BY workspace_id
            ORDER BY usage_count DESC, model_config_id ASC
        ) AS rank
    FROM lightweight_counts
)
UPDATE model_configs mc
SET
    default_model = EXISTS (
        SELECT 1 FROM ranked_main rm
        WHERE rm.model_config_id = mc.id AND rm.rank = 1
    ),
    default_lightweight_model = EXISTS (
        SELECT 1 FROM ranked_lightweight rl
        WHERE rl.model_config_id = mc.id AND rl.rank = 1
    )
"""


def _backfill_agents_sql() -> str:
    """SQL that backfills ModelConfig refs and parameter overrides on Agents."""
    return """
WITH main_configs AS (
    SELECT
        a.id AS agent_id,
        mc.id AS model_config_id
    FROM agents a
    JOIN llm_provider_models pm ON pm.id = a.llm_provider_model_id
    JOIN model_configs mc
      ON mc.workspace_id = a.workspace_id
     AND mc.llm_provider_integration_id = a.llm_provider_integration_id
     AND mc.provider = pm.provider
     AND mc.model_identifier = pm.model_identifier
    WHERE a.llm_provider_integration_id IS NOT NULL
      AND a.llm_provider_model_id IS NOT NULL
), lightweight_configs AS (
    SELECT
        a.id AS agent_id,
        mc.id AS lightweight_model_config_id
    FROM agents a
    JOIN llm_provider_models main_pm ON main_pm.id = a.llm_provider_model_id
    JOIN llm_provider_models compact_pm
      ON compact_pm.provider = main_pm.provider
     AND compact_pm.model_identifier = a.model_parameters ->> 'compaction_model_id'
    JOIN model_configs mc
      ON mc.workspace_id = a.workspace_id
     AND mc.llm_provider_integration_id = a.llm_provider_integration_id
     AND mc.provider = compact_pm.provider
     AND mc.model_identifier = compact_pm.model_identifier
    WHERE jsonb_typeof(a.model_parameters) = 'object'
      AND a.model_parameters ? 'compaction_model_id'
), agent_updates AS (
    SELECT
        a.id AS agent_id,
        main_configs.model_config_id,
        lightweight_configs.lightweight_model_config_id,
        CASE
            WHEN a.role = 'subagent'
             AND a.llm_provider_integration_id IS NULL
             AND a.llm_provider_model_id IS NULL
            THEN 'inherit'::agent_model_config_inherit_mode
            ELSE 'custom'::agent_model_config_inherit_mode
        END AS model_config_inherit_mode,
        CASE
            WHEN a.model_parameters IS NULL THEN NULL
            WHEN jsonb_typeof(a.model_parameters) = 'object'
            THEN NULLIF(a.model_parameters - 'compaction_model_id', '{}'::jsonb)
            ELSE NULL
        END AS model_parameter_overrides
    FROM agents a
    LEFT JOIN main_configs ON main_configs.agent_id = a.id
    LEFT JOIN lightweight_configs ON lightweight_configs.agent_id = a.id
)
UPDATE agents a
SET
    model_config_id = agent_updates.model_config_id,
    lightweight_model_config_id = agent_updates.lightweight_model_config_id,
    model_config_inherit_mode = agent_updates.model_config_inherit_mode,
    model_parameter_overrides = agent_updates.model_parameter_overrides
FROM agent_updates
WHERE a.id = agent_updates.agent_id
"""
