"""remove model config layer"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1d69c2e86ea4"
down_revision: str | Sequence[str] | None = "f0bf7772358f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Migrate the ModelConfig layer to Agent model selection snapshots."""
    op.create_table(
        "workspace_model_settings",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column(
            "default_model_selection",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "default_lightweight_model_selection",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
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
        sa.PrimaryKeyConstraint("workspace_id"),
    )

    op.add_column(
        "agents",
        sa.Column(
            "model_selection",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "lightweight_model_selection",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.execute(sa.text(_assert_inherit_subagents_have_single_parent_model_sql()))
    op.execute(sa.text(_backfill_workspace_model_settings_sql()))
    op.execute(sa.text(_backfill_agents_sql()))
    op.execute(sa.text(_assert_agent_snapshots_backfilled_sql()))

    op.alter_column("agents", "model_selection", nullable=False)
    op.alter_column("agents", "lightweight_model_selection", nullable=False)

    op.drop_constraint(
        "ck_agents_model_not_null_when_role_agent",
        "agents",
        type_="check",
    )
    op.drop_constraint(
        "ck_agents_model_config_inherit_null_refs",
        "agents",
        type_="check",
    )
    op.drop_constraint(
        "ck_agents_model_config_role_agent_custom",
        "agents",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agents_model_not_null",
        "agents",
        "model_selection IS NOT NULL AND lightweight_model_selection IS NOT NULL",
    )

    op.drop_index("ix_agents_lightweight_model_config_id", table_name="agents")
    op.drop_index("ix_agents_model_config_id", table_name="agents")
    op.drop_constraint(
        "fk_agents_lightweight_model_config_id_model_configs",
        "agents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agents_model_config_id_model_configs",
        "agents",
        type_="foreignkey",
    )
    op.drop_constraint("fk_agents_llm_provider_model", "agents", type_="foreignkey")

    op.drop_column("agents", "model_parameter_overrides")
    op.drop_column("agents", "model_config_inherit_mode")
    op.drop_column("agents", "lightweight_model_config_id")
    op.drop_column("agents", "model_config_id")
    op.drop_column("agents", "llm_provider_model_id")
    op.drop_column("agents", "llm_provider_integration_id")

    op.drop_index(
        "uq_model_configs_workspace_default_lightweight_model",
        table_name="model_configs",
    )
    op.drop_index(
        "uq_model_configs_workspace_default_model",
        table_name="model_configs",
    )
    op.drop_index(
        "ix_model_configs_llm_provider_integration_id",
        table_name="model_configs",
    )
    op.drop_index("ix_model_configs_workspace_id", table_name="model_configs")
    op.drop_table("model_configs")

    postgresql.ENUM(name="agent_model_config_inherit_mode").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="model_config_reasoning_effort").drop(
        op.get_bind(), checkfirst=True
    )


def downgrade() -> None:
    """Restore the ModelConfig layer at the schema level."""
    agent_model_config_inherit_mode = postgresql.ENUM(
        "inherit",
        "custom",
        name="agent_model_config_inherit_mode",
        create_type=False,
    )
    model_config_reasoning_effort = postgresql.ENUM(
        "low",
        "medium",
        "high",
        name="model_config_reasoning_effort",
        create_type=False,
    )
    agent_model_config_inherit_mode.create(op.get_bind(), checkfirst=True)
    model_config_reasoning_effort.create(op.get_bind(), checkfirst=True)

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
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("top_p", sa.Float(), nullable=True),
        sa.Column("top_k", sa.Integer(), nullable=True),
        sa.Column("stop_sequences", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("reasoning_effort", model_config_reasoning_effort, nullable=True),
        sa.Column(
            "default_model",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "default_lightweight_model",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
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
    op.create_index("ix_model_configs_workspace_id", "model_configs", ["workspace_id"])
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

    op.add_column(
        "agents",
        sa.Column("llm_provider_integration_id", sa.String(32), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("llm_provider_model_id", sa.String(32), nullable=True),
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
            agent_model_config_inherit_mode,
            nullable=False,
            server_default="custom",
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

    op.execute(sa.text(_downgrade_backfill_legacy_catalog_sql()))
    op.execute(sa.text(_downgrade_backfill_model_configs_sql()))
    op.execute(sa.text(_downgrade_backfill_agents_sql()))

    op.drop_constraint("ck_agents_model_not_null", "agents", type_="check")
    op.create_check_constraint(
        "ck_agents_model_not_null_when_role_agent",
        "agents",
        "role = 'subagent' OR "
        "(model_config_id IS NOT NULL OR "
        "(llm_provider_model_id IS NOT NULL AND "
        "llm_provider_integration_id IS NOT NULL))",
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

    op.create_foreign_key(
        "fk_agents_llm_provider_model",
        "agents",
        "llm_provider_models",
        ["llm_provider_model_id"],
        ["id"],
        ondelete="RESTRICT",
    )
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

    op.drop_column("agents", "lightweight_model_selection")
    op.drop_column("agents", "model_selection")
    op.drop_table("workspace_model_settings")


def _downgrade_backfill_legacy_catalog_sql() -> str:
    """SQL that restores legacy LLM catalog rows required by Agent snapshots."""
    return """
WITH selections AS (
    SELECT a.model_selection AS selection
    FROM agents a
    WHERE a.model_selection IS NOT NULL
    UNION
    SELECT a.lightweight_model_selection AS selection
    FROM agents a
    WHERE a.lightweight_model_selection IS NOT NULL
), distinct_selections AS (
    SELECT DISTINCT ON (
        selection ->> 'provider',
        selection ->> 'model_identifier'
    )
        selection,
        concat(
            'downgrade-',
            md5(
                (selection ->> 'provider') || ':' ||
                (selection ->> 'model_identifier')
            )
        ) AS model_slug
    FROM selections
    WHERE selection IS NOT NULL
    ORDER BY selection ->> 'provider', selection ->> 'model_identifier'
)
INSERT INTO llm_models (
    slug,
    model_developer,
    name,
    description,
    source_key,
    source_model_id,
    created_at,
    updated_at
)
SELECT
    model_slug,
    (selection ->> 'model_developer')::llm_model_developer,
    selection ->> 'model_display_name',
    NULL,
    NULL,
    selection ->> 'model_identifier',
    now(),
    now()
FROM distinct_selections
WHERE NOT EXISTS (
    SELECT 1 FROM llm_provider_models pm
    WHERE pm.provider = (selection ->> 'provider')::llm_provider
      AND pm.model_identifier = selection ->> 'model_identifier'
)
ON CONFLICT (slug) DO NOTHING;

WITH selections AS (
    SELECT a.model_selection AS selection
    FROM agents a
    WHERE a.model_selection IS NOT NULL
    UNION
    SELECT a.lightweight_model_selection AS selection
    FROM agents a
    WHERE a.lightweight_model_selection IS NOT NULL
), distinct_selections AS (
    SELECT DISTINCT ON (
        selection ->> 'provider',
        selection ->> 'model_identifier'
    )
        selection,
        concat(
            'downgrade-',
            md5(
                (selection ->> 'provider') || ':' ||
                (selection ->> 'model_identifier')
            )
        ) AS model_slug
    FROM selections
    WHERE selection IS NOT NULL
    ORDER BY selection ->> 'provider', selection ->> 'model_identifier'
)
INSERT INTO llm_provider_models (
    id,
    provider,
    model_identifier,
    model_slug,
    capabilities,
    available,
    thinking,
    metadata,
    lifecycle_status,
    raw_source_metadata,
    source_key,
    source_record_id,
    last_synced_at,
    created_at,
    updated_at
)
SELECT
    md5(
        'downgrade_provider_model:' ||
        (selection ->> 'provider') || ':' ||
        (selection ->> 'model_identifier')
    ),
    (selection ->> 'provider')::llm_provider,
    selection ->> 'model_identifier',
    model_slug,
    selection -> 'normalized_capabilities',
    true,
    COALESCE(
        (selection #>> '{normalized_capabilities,reasoning,supported}')::boolean,
        false
    ),
    '{}'::jsonb,
    'local_only'::llm_model_lifecycle_status,
    selection -> 'source_metadata',
    NULL,
    concat(selection ->> 'provider', '/', selection ->> 'model_identifier'),
    (selection ->> 'last_refreshed_at')::timestamptz,
    now(),
    now()
FROM distinct_selections
ON CONFLICT (provider, model_identifier) DO NOTHING
"""


def _downgrade_backfill_model_configs_sql() -> str:
    """SQL that restores Agent snapshots to legacy ModelConfig rows."""
    return """
WITH selections AS (
    SELECT
        a.workspace_id,
        a.model_selection AS selection,
        false AS default_lightweight_model
    FROM agents a
    WHERE a.model_selection IS NOT NULL
    UNION
    SELECT
        a.workspace_id,
        a.lightweight_model_selection AS selection,
        true AS default_lightweight_model
    FROM agents a
    WHERE a.lightweight_model_selection IS NOT NULL
), distinct_selections AS (
    SELECT DISTINCT ON (
        workspace_id,
        selection ->> 'llm_provider_integration_id',
        selection ->> 'provider',
        selection ->> 'model_identifier'
    )
        workspace_id,
        selection,
        false AS default_lightweight_model
    FROM selections
    WHERE selection IS NOT NULL
    ORDER BY
        workspace_id,
        selection ->> 'llm_provider_integration_id',
        selection ->> 'provider',
        selection ->> 'model_identifier'
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
    temperature,
    max_tokens,
    top_p,
    top_k,
    stop_sequences,
    reasoning_effort,
    default_model,
    default_lightweight_model,
    enabled,
    last_refreshed_at,
    created_at,
    updated_at
)
SELECT
    md5(
        'downgrade_model_config:' || workspace_id || ':' ||
        (selection ->> 'llm_provider_integration_id') || ':' ||
        (selection ->> 'provider') || ':' ||
        (selection ->> 'model_identifier')
    ),
    workspace_id,
    concat('Restored ', left(selection ->> 'model_identifier', 200)),
    selection ->> 'llm_provider_integration_id',
    (selection ->> 'provider')::llm_provider,
    selection ->> 'model_identifier',
    selection ->> 'model_display_name',
    (selection ->> 'model_developer')::llm_model_developer,
    selection ->> 'model_family',
    selection -> 'normalized_capabilities',
    selection -> 'model_snapshot',
    selection -> 'source_metadata',
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    false,
    default_lightweight_model,
    true,
    (selection ->> 'last_refreshed_at')::timestamptz,
    now(),
    now()
FROM distinct_selections
ON CONFLICT (id) DO NOTHING
"""


def _downgrade_backfill_agents_sql() -> str:
    """SQL that restores Agent legacy model_config refs from snapshots."""
    return """
WITH main_refs AS (
    SELECT
        a.id AS agent_id,
        mc.id AS model_config_id,
        pm.id AS llm_provider_model_id,
        mc.llm_provider_integration_id
    FROM agents a
    JOIN model_configs mc
      ON mc.workspace_id = a.workspace_id
     AND mc.llm_provider_integration_id =
         a.model_selection ->> 'llm_provider_integration_id'
     AND mc.provider = (a.model_selection ->> 'provider')::llm_provider
     AND mc.model_identifier = a.model_selection ->> 'model_identifier'
    LEFT JOIN llm_provider_models pm
      ON pm.provider = mc.provider
     AND pm.model_identifier = mc.model_identifier
), lightweight_refs AS (
    SELECT
        a.id AS agent_id,
        mc.id AS lightweight_model_config_id
    FROM agents a
    JOIN model_configs mc
      ON mc.workspace_id = a.workspace_id
     AND mc.llm_provider_integration_id =
         a.lightweight_model_selection ->> 'llm_provider_integration_id'
     AND mc.provider = (a.lightweight_model_selection ->> 'provider')::llm_provider
     AND mc.model_identifier = a.lightweight_model_selection ->> 'model_identifier'
)
UPDATE agents a
SET
    model_config_id = main_refs.model_config_id,
    lightweight_model_config_id = lightweight_refs.lightweight_model_config_id,
    llm_provider_integration_id = main_refs.llm_provider_integration_id,
    llm_provider_model_id = main_refs.llm_provider_model_id,
    model_parameter_overrides = a.model_parameters
FROM main_refs
LEFT JOIN lightweight_refs ON lightweight_refs.agent_id = main_refs.agent_id
WHERE a.id = main_refs.agent_id
"""


def _model_selection_sql(alias: str) -> str:
    """SQL expression that converts ModelConfig rows to AgentModelSelection JSONB."""
    return f"""
CASE
    WHEN {alias}.id IS NULL THEN NULL
    ELSE jsonb_build_object(
        'llm_provider_integration_id', {alias}.llm_provider_integration_id,
        'provider', {alias}.provider,
        'model_identifier', {alias}.model_identifier,
        'model_display_name', {alias}.model_display_name,
        'model_developer', {alias}.model_developer,
        'model_family', to_jsonb({alias}.model_family),
        'normalized_capabilities', {alias}.normalized_capabilities,
        'model_snapshot', {alias}.model_snapshot,
        'source_metadata', to_jsonb({alias}.source_metadata),
        'last_refreshed_at', to_jsonb({alias}.last_refreshed_at)
    )
END
"""


def _model_parameters_sql(model_config_alias: str, overrides_expr: str) -> str:
    """SQL expression that merges ModelConfig parameters and Agent overrides."""
    return f"""
NULLIF(
    jsonb_strip_nulls(jsonb_build_object(
        'temperature', to_jsonb({model_config_alias}.temperature),
        'max_tokens', to_jsonb({model_config_alias}.max_tokens),
        'top_p', to_jsonb({model_config_alias}.top_p),
        'top_k', to_jsonb({model_config_alias}.top_k),
        'stop_sequences', to_jsonb({model_config_alias}.stop_sequences),
        'reasoning_effort', to_jsonb({model_config_alias}.reasoning_effort)
    )) || COALESCE({overrides_expr}, '{{}}'::jsonb),
    '{{}}'::jsonb
)
"""


def _assert_inherit_subagents_have_single_parent_model_sql() -> str:
    """Verify that legacy inherit subagents have unambiguous parent model sources."""
    return """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM agents s
        LEFT JOIN agent_subagents j ON j.subagent_id = s.id
        LEFT JOIN agents p ON p.id = j.agent_id
        WHERE s.role = 'subagent'
          AND s.model_config_inherit_mode = 'inherit'
        GROUP BY s.id
        HAVING count(DISTINCT p.id) != 1
           OR count(DISTINCT p.model_config_id) != 1
    ) THEN
        RAISE EXCEPTION
            'cannot migrate inherited subagent with zero or ambiguous parent model';
    END IF;
END $$
"""


def _backfill_workspace_model_settings_sql() -> str:
    """Migrate ModelConfig default flags to workspace default snapshots."""
    main_selection = _model_selection_sql("main_mc")
    lightweight_selection = _model_selection_sql("lw_mc")
    return f"""
INSERT INTO workspace_model_settings (
    workspace_id,
    default_model_selection,
    default_lightweight_model_selection,
    created_at,
    updated_at
)
SELECT
    w.id,
    {main_selection},
    {lightweight_selection},
    now(),
    now()
FROM workspaces w
LEFT JOIN model_configs main_mc
  ON main_mc.workspace_id = w.id
 AND main_mc.default_model IS TRUE
LEFT JOIN model_configs lw_mc
  ON lw_mc.workspace_id = w.id
 AND lw_mc.default_lightweight_model IS TRUE
WHERE main_mc.id IS NOT NULL OR lw_mc.id IS NOT NULL
"""


def _backfill_agents_sql() -> str:
    """Migrate Agent ModelConfig refs to Agent-local snapshots."""
    own_selection = _model_selection_sql("own_mc")
    parent_selection = _model_selection_sql("parent_mc")
    own_lightweight_selection = _model_selection_sql("own_lw_mc")
    workspace_lightweight_selection = _model_selection_sql("workspace_lw_mc")
    parent_lightweight_selection = _model_selection_sql("parent_lw_mc")
    own_parameters = _model_parameters_sql(
        "own_mc",
        "a.model_parameter_overrides",
    )
    parent_parameters = _model_parameters_sql(
        "parent_mc",
        "a.model_parameter_overrides",
    )
    return f"""
WITH inherited_parent AS (
    SELECT
        s.id AS agent_id,
        min(p.model_config_id) AS model_config_id,
        min(p.lightweight_model_config_id) AS lightweight_model_config_id
    FROM agents s
    JOIN agent_subagents j ON j.subagent_id = s.id
    JOIN agents p ON p.id = j.agent_id
    WHERE s.role = 'subagent'
      AND s.model_config_inherit_mode = 'inherit'
    GROUP BY s.id
), resolved AS (
    SELECT
        a.id AS agent_id,
        CASE
            WHEN a.model_config_inherit_mode = 'inherit'
            THEN {parent_selection}
            ELSE {own_selection}
        END AS model_selection,
        CASE
            WHEN a.model_config_inherit_mode = 'inherit'
            THEN COALESCE(
                {parent_lightweight_selection},
                {parent_selection}
            )
            ELSE COALESCE(
                {own_lightweight_selection},
                {workspace_lightweight_selection},
                {own_selection}
            )
        END AS lightweight_model_selection,
        CASE
            WHEN a.model_config_inherit_mode = 'inherit'
            THEN {parent_parameters}
            ELSE {own_parameters}
        END AS model_parameters
    FROM agents a
    LEFT JOIN inherited_parent ip ON ip.agent_id = a.id
    LEFT JOIN model_configs own_mc ON own_mc.id = a.model_config_id
    LEFT JOIN model_configs own_lw_mc ON own_lw_mc.id = a.lightweight_model_config_id
    LEFT JOIN model_configs parent_mc ON parent_mc.id = ip.model_config_id
    LEFT JOIN model_configs parent_lw_mc
      ON parent_lw_mc.id = ip.lightweight_model_config_id
    LEFT JOIN workspace_model_settings wms ON wms.workspace_id = a.workspace_id
    LEFT JOIN model_configs workspace_lw_mc
      ON workspace_lw_mc.workspace_id = a.workspace_id
     AND workspace_lw_mc.default_lightweight_model IS TRUE
)
UPDATE agents a
SET
    model_selection = resolved.model_selection,
    lightweight_model_selection = resolved.lightweight_model_selection,
    model_parameters = resolved.model_parameters
FROM resolved
WHERE a.id = resolved.agent_id
"""


def _assert_agent_snapshots_backfilled_sql() -> str:
    """Verify that every Agent snapshot has been populated."""
    return """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM agents
        WHERE model_selection IS NULL OR lightweight_model_selection IS NULL
    ) THEN
        RAISE EXCEPTION 'agent model selection snapshot backfill failed';
    END IF;
END $$
"""
