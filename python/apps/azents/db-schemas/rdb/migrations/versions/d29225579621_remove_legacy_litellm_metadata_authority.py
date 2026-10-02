"""Remove legacy model metadata authority.

Revision ID: d29225579621
Revises: 91dd4bb71ef6
Create Date: 2026-10-01 14:23:58.225572

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d29225579621"
down_revision: str | Sequence[str] | None = "91dd4bb71ef6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Guard the completed cutover and remove irreversible legacy state."""
    op.execute(
        "LOCK TABLE model_metadata_sources, model_metadata_source_snapshots, "
        "llm_catalogs, llm_catalog_snapshots, llm_catalog_sync_attempts, "
        "llm_catalog_entries, litellm_source_snapshots, scheduled_task_states "
        "IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM llm_catalog_sync_attempts WHERE status = 'running'
              ) THEN
                RAISE EXCEPTION 'catalog attempts are still running';
              END IF;
              UPDATE llm_catalogs AS c
              SET current_snapshot_id = NULL
              WHERE c.purpose = 'conversation'
                AND c.current_snapshot_id IS NOT NULL
                AND (
                  NOT EXISTS (
                    SELECT 1
                    FROM llm_catalog_snapshots AS s
                    JOIN model_metadata_source_snapshots AS ms
                      ON ms.id = s.metadata_source_snapshot_id
                    WHERE s.id = c.current_snapshot_id
                      AND s.catalog_id = c.id
                      AND s.projection_schema_version IS NOT NULL
                      AND s.runtime_profile_resolver_revision IS NOT NULL
                      AND s.pydantic_ai_version IS NOT NULL
                      AND s.genai_prices_version IS NOT NULL
                      AND s.projection_fingerprint IS NOT NULL
                      AND ms.source_key = 'genai_prices'
                  )
                  OR EXISTS (
                    SELECT 1
                    FROM llm_catalog_entries AS e
                    WHERE e.catalog_id = c.id
                      AND e.snapshot_id = c.current_snapshot_id
                      AND (
                        COALESCE(e.source_metadata, '{}'::jsonb)::text ~
                          '"(litellm_provider|source_model_key|target_projection_key|target_metadata|target_metadata_match_required|exact_projection_key)"[[:space:]]*:'
                        OR COALESCE(e.projection_metadata, '{}'::jsonb)::text ~
                          '"(litellm_provider|source_model_key|target_projection_key|target_metadata|target_metadata_match_required|exact_projection_key)"[[:space:]]*:'
                      )
                  )
                );
              IF EXISTS (
                SELECT 1
                FROM llm_catalogs
                WHERE purpose = 'conversation'
                  AND current_snapshot_id IS NOT NULL
              ) AND NOT EXISTS (
                SELECT 1
                FROM model_metadata_sources AS source
                JOIN model_metadata_source_snapshots AS snapshot
                  ON snapshot.id = source.current_snapshot_id
                WHERE source.source_key = 'genai_prices'
                  AND snapshot.source_key = 'genai_prices'
              ) THEN
                RAISE EXCEPTION 'generic model metadata source is unavailable';
              END IF;
              IF EXISTS (
                SELECT 1
                FROM llm_catalogs AS c
                JOIN llm_catalog_entries AS e
                  ON e.catalog_id = c.id
                 AND e.snapshot_id = c.current_snapshot_id
                WHERE c.purpose = 'conversation'
                  AND (
                    COALESCE(e.source_metadata, '{}'::jsonb)::text ~
                      '"(litellm_provider|source_model_key|target_projection_key|target_metadata|target_metadata_match_required|exact_projection_key)"[[:space:]]*:'
                    OR COALESCE(e.projection_metadata, '{}'::jsonb)::text ~
                      '"(litellm_provider|source_model_key|target_projection_key|target_metadata|target_metadata_match_required|exact_projection_key)"[[:space:]]*:'
                  )
              ) THEN
                RAISE EXCEPTION 'current conversation entry retains legacy metadata';
              END IF;
              IF EXISTS (
                SELECT 1
                FROM llm_catalogs AS c
                LEFT JOIN llm_catalog_snapshots AS s ON s.id = c.rollback_snapshot_id
                WHERE c.rollback_snapshot_id IS NOT NULL
                  AND (
                    c.scope <> 'system'
                    OR c.purpose <> 'conversation'
                    OR s.catalog_id IS DISTINCT FROM c.id
                    OR s.id = c.current_snapshot_id
                    OR s.metadata_source_snapshot_id IS NOT NULL
                  )
              ) THEN
                RAISE EXCEPTION 'rollback pins are not valid pre-cutover snapshots';
              END IF;
            END
            $$
            """
        )
    )
    op.execute(
        "CREATE TEMP TABLE legacy_catalog_snapshots ON COMMIT DROP AS "
        "SELECT s.id FROM llm_catalog_snapshots AS s "
        "JOIN llm_catalogs AS c ON c.id = s.catalog_id "
        "WHERE c.purpose = 'conversation' "
        "AND s.id IS DISTINCT FROM c.current_snapshot_id "
        "AND (s.metadata_source_snapshot_id IS NULL OR EXISTS ("
        "SELECT 1 FROM llm_catalog_entries AS e "
        "WHERE e.catalog_id = c.id AND e.snapshot_id = s.id AND ("
        "COALESCE(e.source_metadata, '{}'::jsonb)::text ~ "
        "'\"(litellm_provider|source_model_key|target_projection_key|"
        "target_metadata|target_metadata_match_required|exact_projection_key)"
        "\"[[:space:]]*:' "
        "OR COALESCE(e.projection_metadata, '{}'::jsonb)::text ~ "
        "'\"(litellm_provider|source_model_key|target_projection_key|"
        "target_metadata|target_metadata_match_required|exact_projection_key)"
        "\"[[:space:]]*:'"
        ")))"
    )
    op.execute(
        "UPDATE llm_catalogs AS c SET latest_attempt_id = ("
        "SELECT a.id FROM llm_catalog_sync_attempts AS a "
        "WHERE a.catalog_id = c.id AND a.source_key <> 'litellm_model_cost' "
        "ORDER BY a.started_at DESC, a.id DESC LIMIT 1) "
        "WHERE c.latest_attempt_id IN (SELECT id FROM llm_catalog_sync_attempts "
        "WHERE source_key = 'litellm_model_cost')"
    )
    op.execute(
        "DELETE FROM llm_catalog_sync_attempts WHERE source_key = 'litellm_model_cost'"
    )
    op.execute(
        "DELETE FROM scheduled_task_states WHERE task_key IN "
        "('model_catalog_integration_reprojection', "
        "'model_metadata_shadow_projection')"
    )
    op.execute("UPDATE llm_catalogs SET rollback_snapshot_id = NULL")
    op.execute(
        "DELETE FROM llm_catalog_snapshots "
        "WHERE id IN (SELECT id FROM legacy_catalog_snapshots)"
    )
    op.drop_column("llm_catalogs", "rollback_snapshot_id")
    op.drop_constraint(
        "llm_catalog_snapshots_source_snapshot_id_fkey",
        "llm_catalog_snapshots",
        type_="foreignkey",
    )
    op.drop_column("llm_catalog_snapshots", "source_snapshot_id")
    op.drop_index(
        "ix_llm_catalog_snapshots_metadata_source_snapshot_id",
        table_name="llm_catalog_snapshots",
    )
    op.drop_constraint(
        "llm_catalog_snapshots_metadata_source_snapshot_id_fkey",
        "llm_catalog_snapshots",
        type_="foreignkey",
    )
    op.alter_column(
        "llm_catalog_snapshots",
        "metadata_source_snapshot_id",
        new_column_name="source_snapshot_id",
    )
    op.create_foreign_key(
        "llm_catalog_snapshots_source_snapshot_id_fkey",
        "llm_catalog_snapshots",
        "model_metadata_source_snapshots",
        ["source_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        "ix_llm_catalog_snapshots_source_snapshot_id",
        "llm_catalog_snapshots",
        ["source_snapshot_id"],
        unique=False,
    )
    op.drop_table("litellm_source_snapshots")


def downgrade() -> None:
    """Reject downgrade because cleanup deletes authoritative historical state."""
    raise RuntimeError("The model metadata cleanup migration is irreversible.")
