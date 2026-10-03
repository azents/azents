"""Align repository indexes and preserve active/historical source-kind values."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1c42cc5ce89f"
down_revision: str | Sequence[str] | None = "c8bc0a5dcab0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_RENAMES = (
    (
        "ix_historical_memory_sources_admitted_unprepared",
        "ix_historical_memory_sources_admitted_at",
    ),
    (
        "ix_model_metadata_source_snapshots_source_created",
        "ix_model_metadata_source_snapshots_source_key_created_at",
    ),
    (
        "uq_llm_catalogs_system_scope_provider_purpose",
        "ix_llm_catalogs_provider_purpose",
    ),
    (
        "uq_llm_catalogs_integration_purpose",
        "ix_llm_catalogs_provider_integration_id_purpose",
    ),
    (
        "ix_llm_catalog_entries_catalog_display",
        "ix_llm_catalog_entries_catalog_id_display_name",
    ),
    (
        "ix_llm_catalog_entries_catalog_model",
        "ix_llm_catalog_entries_catalog_id_provider_model_identifier",
    ),
    (
        "uq_agent_toolkit_namespace_reservations_active_agent_toolkit",
        "ix_agent_toolkit_namespace_reservations_agent_id_toolkit_id",
    ),
)

_PREFLIGHT_SQL = """
DO $$
BEGIN
  IF current_setting('session_replication_role') <> 'origin' THEN
    RAISE EXCEPTION 'Source-kind conversion requires active origin writer guards.';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM (
      VALUES
        ('model_metadata_sources', 'guard_model_source_authority',
         'azents_guard_model_source_authority', 31),
        ('model_metadata_source_snapshots', 'guard_model_source_snapshot',
         'azents_guard_model_source_snapshot', 31),
        ('llm_catalog_snapshots', 'guard_catalog_snapshot',
         'azents_guard_catalog_snapshot', 23),
        ('llm_catalogs', 'guard_catalog_authority',
         'azents_guard_catalog_authority', 23),
        ('llm_catalog_sync_attempts', 'guard_retired_source_attempt',
         'azents_guard_retired_source_attempt', 23)
    ) AS expected(table_name, trigger_name, function_name, trigger_type)
    LEFT JOIN pg_trigger AS installed
      ON installed.tgrelid = to_regclass(expected.table_name)
     AND installed.tgname = expected.trigger_name
    LEFT JOIN pg_proc AS guard_function ON guard_function.oid = installed.tgfoid
    WHERE installed.oid IS NULL
       OR installed.tgisinternal
       OR installed.tgenabled <> 'O'
       OR installed.tgtype <> expected.trigger_type
       OR guard_function.proname IS DISTINCT FROM expected.function_name
  ) THEN
    RAISE EXCEPTION 'Source-kind conversion requires the installed cutover guards.';
  END IF;
  IF EXISTS (
    SELECT 1 FROM model_metadata_source_snapshots
    WHERE source_kind IS NULL
       OR source_kind NOT IN ('genai_prices', 'litellm_json')
       OR source_key NOT IN ('genai_prices', 'litellm_catalog')
       OR (source_key = 'genai_prices' AND source_kind <> 'genai_prices')
       OR (source_key = 'litellm_catalog' AND (
         source_kind <> 'litellm_json' OR source_schema_version <> '1'
       ))
  ) THEN
    RAISE EXCEPTION 'Source-kind inventory contains an unsupported source contract.';
  END IF;
  IF EXISTS (
    SELECT 1 FROM model_metadata_sources AS authority
    LEFT JOIN model_metadata_source_snapshots AS snapshot
      ON snapshot.id = authority.current_snapshot_id
    WHERE authority.current_snapshot_id IS NOT NULL
      AND (
        snapshot.id IS NULL
        OR snapshot.source_key IS DISTINCT FROM authority.source_key
        OR authority.source_key <> 'litellm_catalog'
        OR snapshot.source_kind <> 'litellm_json'
        OR snapshot.source_schema_version <> '1'
      )
  ) THEN
    RAISE EXCEPTION 'Source-kind inventory has an inconsistent current authority.';
  END IF;
  IF EXISTS (
    SELECT 1 FROM llm_catalogs AS catalog
    LEFT JOIN llm_catalog_snapshots AS snapshot
      ON snapshot.id = catalog.current_snapshot_id
    WHERE catalog.current_snapshot_id IS NOT NULL
      AND (
        snapshot.id IS NULL
        OR snapshot.catalog_id IS DISTINCT FROM catalog.id
      )
  ) THEN
    RAISE EXCEPTION 'Source-kind inventory has inconsistent catalog ownership.';
  END IF;
END
$$;
"""


def _source_kind_type() -> postgresql.ENUM:
    """Declare both legal persisted contracts without importing mutable app code."""
    return postgresql.ENUM(
        "genai_prices",
        "litellm_json",
        name="model_metadata_source_kind",
        create_type=False,
    )


def upgrade() -> None:
    """Validate prior writer authority, then perform lossless schema-only changes."""
    op.execute(sa.text(_PREFLIGHT_SQL))
    kind_type = _source_kind_type()
    kind_type.create(op.get_bind(), checkfirst=False)
    op.alter_column(
        "model_metadata_source_snapshots",
        "source_kind",
        existing_type=sa.String(40),
        type_=kind_type,
        existing_nullable=False,
        postgresql_using="source_kind::model_metadata_source_kind",
    )
    for old_name, new_name in _INDEX_RENAMES:
        op.execute(sa.text(f"ALTER INDEX {old_name} RENAME TO {new_name}"))


def downgrade() -> None:
    """Restore predecessor schema names/types without deleting source history."""
    for old_name, new_name in reversed(_INDEX_RENAMES):
        op.execute(sa.text(f"ALTER INDEX {new_name} RENAME TO {old_name}"))
    op.alter_column(
        "model_metadata_source_snapshots",
        "source_kind",
        existing_type=_source_kind_type(),
        type_=sa.String(40),
        existing_nullable=False,
        postgresql_using="source_kind::text",
    )
    _source_kind_type().drop(op.get_bind(), checkfirst=False)
