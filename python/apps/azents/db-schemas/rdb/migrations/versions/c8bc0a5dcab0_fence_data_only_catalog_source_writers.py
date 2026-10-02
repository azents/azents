"""Fence the data-only catalog source while preserving historical projections."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8bc0a5dcab0"
down_revision: str | Sequence[str] | None = "459a4285993c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install the SQL-only writer contract under one fixed table-lock order."""
    # Stop/drain old save and dispatch producers before this migration is exposed.
    # Database guards cannot revoke their previously captured in-memory records.
    op.execute(
        "LOCK TABLE model_metadata_sources, model_metadata_source_snapshots, "
        "llm_catalogs, llm_catalog_snapshots, llm_catalog_sync_attempts "
        "IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        sa.text("""
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM model_metadata_sources AS a
            LEFT JOIN model_metadata_source_snapshots AS s
              ON s.id = a.current_snapshot_id
            WHERE a.current_snapshot_id IS NOT NULL
              AND (s.id IS NULL OR s.source_key IS DISTINCT FROM a.source_key)
          ) THEN
            RAISE EXCEPTION 'Model source current pointer is inconsistent.';
          END IF;
          IF EXISTS (
            SELECT 1 FROM llm_catalogs AS c
            LEFT JOIN llm_catalog_snapshots AS s
              ON s.id = c.current_snapshot_id
            WHERE c.current_snapshot_id IS NOT NULL
              AND (s.id IS NULL OR s.catalog_id IS DISTINCT FROM c.id)
          ) THEN
            RAISE EXCEPTION 'Catalog current pointer is inconsistent.';
          END IF;
          IF EXISTS (
            SELECT 1 FROM model_metadata_sources
            WHERE source_key = 'litellm_catalog'
              AND current_snapshot_id IS NOT NULL
          ) THEN
            RAISE EXCEPTION
              'Replacement source must be inactive before writer cutover.';
          END IF;
        END $$
    """)
    )
    op.execute(
        sa.text("""
        UPDATE model_metadata_sources
        SET current_snapshot_id = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE source_key = 'genai_prices';

        INSERT INTO model_metadata_sources
          (source_key, current_snapshot_id, latest_attempt_id)
        VALUES ('litellm_catalog', NULL, NULL)
        ON CONFLICT (source_key) DO NOTHING;

        UPDATE llm_catalog_sync_attempts
        SET status = 'failed', finished_at = CURRENT_TIMESTAMP,
            failure_code = 'ModelMetadataSourceRetired',
            failure_message = 'The source writer contract was retired.',
            action_hint = 'Use the replacement source synchronization.',
            diagnostics = jsonb_build_object(
              'failure_category', 'retired_source_cutover',
              'migration_revision', 'c8bc0a5dcab0'
            )
        WHERE source_key = 'genai_prices' AND status = 'running'
    """)
    )
    op.create_foreign_key(
        "fk_model_metadata_sources_current_snapshot",
        "model_metadata_sources",
        "model_metadata_source_snapshots",
        ["current_snapshot_id"],
        ["id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_llm_catalogs_current_snapshot",
        "llm_catalogs",
        "llm_catalog_snapshots",
        ["current_snapshot_id"],
        ["id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )
    op.drop_constraint(
        "llm_catalog_snapshots_source_snapshot_id_fkey",
        "llm_catalog_snapshots",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "llm_catalog_snapshots_source_snapshot_id_fkey",
        "llm_catalog_snapshots",
        "model_metadata_source_snapshots",
        ["source_snapshot_id"],
        ["id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )
    op.execute(
        sa.text("""
        CREATE FUNCTION azents_check_catalog_source(snapshot_id varchar)
        RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM model_metadata_source_snapshots AS s
            WHERE s.id = snapshot_id
              AND s.source_key = 'litellm_catalog'
              AND s.source_kind = 'litellm_json'
              AND s.source_schema_version = '1'
          ) THEN
            RAISE EXCEPTION 'Model source reference uses an incompatible contract.'
              USING ERRCODE = '23514';
          END IF;
        END $$;

        CREATE FUNCTION azents_check_catalog_candidate(
          owner_id varchar, snapshot_id varchar
        ) RETURNS void LANGUAGE plpgsql AS $$
        DECLARE
          owner llm_catalogs%ROWTYPE;
          candidate llm_catalog_snapshots%ROWTYPE;
        BEGIN
          SELECT * INTO owner FROM llm_catalogs WHERE id = owner_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'Catalog owner does not exist.'
              USING ERRCODE = '23503';
          END IF;
          SELECT * INTO candidate FROM llm_catalog_snapshots
            WHERE id = snapshot_id;
          IF NOT FOUND OR candidate.catalog_id IS DISTINCT FROM owner.id THEN
            RAISE EXCEPTION 'Catalog pointer does not reference its owner.'
              USING ERRCODE = '23514';
          END IF;
          IF owner.purpose = 'image_generation' THEN
            RETURN;
          END IF;
          IF candidate.projection_schema_version IS DISTINCT FROM '2'
            OR candidate.genai_prices_version IS NOT NULL THEN
            RAISE EXCEPTION 'Catalog candidate uses an incompatible projection.'
              USING ERRCODE = '23514';
          END IF;
          IF candidate.source_snapshot_id IS NULL THEN
            IF owner.scope = 'system' THEN
              RAISE EXCEPTION 'System catalog candidate requires a new source.'
                USING ERRCODE = '23514';
            END IF;
          ELSE
            PERFORM azents_check_catalog_source(candidate.source_snapshot_id);
          END IF;
        END $$;

        CREATE FUNCTION azents_guard_model_source_authority()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.source_key = 'genai_prices' THEN
              RAISE EXCEPTION 'Retired model source authority is frozen.'
                USING ERRCODE = '23514';
            END IF;
            RETURN OLD;
          END IF;
          IF NEW.source_key = 'genai_prices' OR
            (TG_OP = 'UPDATE' AND OLD.source_key = 'genai_prices') THEN
            RAISE EXCEPTION 'Retired model source authority is frozen.'
              USING ERRCODE = '23514';
          END IF;
          IF NEW.current_snapshot_id IS NOT NULL THEN
            IF NEW.source_key IS DISTINCT FROM 'litellm_catalog' THEN
              RAISE EXCEPTION 'Model source authority uses an incompatible key.'
                USING ERRCODE = '23514';
            END IF;
            PERFORM azents_check_catalog_source(NEW.current_snapshot_id);
          END IF;
          RETURN NEW;
        END $$;

        CREATE FUNCTION azents_guard_model_source_snapshot()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.source_key = 'genai_prices' THEN
              RAISE EXCEPTION 'Retired model source snapshots are frozen.'
                USING ERRCODE = '23514';
            END IF;
            RETURN OLD;
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.source_key = 'genai_prices' THEN
            RAISE EXCEPTION 'Retired model source snapshots are frozen.'
              USING ERRCODE = '23514';
          END IF;
          IF NEW.source_key IS DISTINCT FROM 'litellm_catalog'
            OR NEW.source_kind IS DISTINCT FROM 'litellm_json'
            OR NEW.source_schema_version IS DISTINCT FROM '1' THEN
            RAISE EXCEPTION 'Model source snapshot uses an incompatible contract.'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;

        CREATE FUNCTION azents_guard_catalog_snapshot()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          owner llm_catalogs%ROWTYPE;
        BEGIN
          IF TG_OP = 'UPDATE' AND (
            NEW.id IS DISTINCT FROM OLD.id
            OR NEW.catalog_id IS DISTINCT FROM OLD.catalog_id
          ) THEN
            RAISE EXCEPTION 'Catalog snapshot ownership is immutable.'
              USING ERRCODE = '23514';
          END IF;
          SELECT * INTO owner FROM llm_catalogs WHERE id = NEW.catalog_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'Catalog snapshot owner does not exist.'
              USING ERRCODE = '23503';
          END IF;
          IF owner.purpose = 'image_generation' THEN
            RETURN NEW;
          END IF;
          IF NEW.projection_schema_version IS DISTINCT FROM '2'
            OR NEW.genai_prices_version IS NOT NULL THEN
            RAISE EXCEPTION 'Catalog candidate uses an incompatible projection.'
              USING ERRCODE = '23514';
          END IF;
          IF NEW.source_snapshot_id IS NULL THEN
            IF owner.scope = 'system' THEN
              RAISE EXCEPTION 'System catalog candidate requires a new source.'
                USING ERRCODE = '23514';
            END IF;
          ELSE
            PERFORM azents_check_catalog_source(NEW.source_snapshot_id);
          END IF;
          RETURN NEW;
        END $$;

        CREATE FUNCTION azents_guard_catalog_authority()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF NEW.id IS DISTINCT FROM OLD.id
              OR NEW.scope IS DISTINCT FROM OLD.scope
              OR NEW.provider IS DISTINCT FROM OLD.provider
              OR NEW.purpose IS DISTINCT FROM OLD.purpose
              OR NEW.provider_integration_id IS DISTINCT FROM
                OLD.provider_integration_id THEN
              RAISE EXCEPTION 'Catalog ownership and purpose are immutable.'
                USING ERRCODE = '23514';
            END IF;
            IF NEW.current_snapshot_id IS NOT DISTINCT FROM
              OLD.current_snapshot_id THEN
              RETURN NEW;
            END IF;
            IF NEW.current_snapshot_id IS NULL
              AND OLD.current_snapshot_id IS NOT NULL THEN
              RAISE EXCEPTION 'A successful catalog pointer cannot be cleared.'
                USING ERRCODE = '23514';
            END IF;
          END IF;
          IF NEW.current_snapshot_id IS NOT NULL THEN
            PERFORM azents_check_catalog_candidate(NEW.id, NEW.current_snapshot_id);
          END IF;
          RETURN NEW;
        END $$;

        CREATE FUNCTION azents_guard_retired_source_attempt()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.source_key = 'genai_prices' AND NEW.status = 'succeeded'
            AND (
              TG_OP = 'INSERT'
              OR OLD.status IS DISTINCT FROM NEW.status
              OR OLD.produced_snapshot_id IS DISTINCT FROM NEW.produced_snapshot_id
            ) THEN
            RAISE EXCEPTION 'Retired source attempts cannot publish success.'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER guard_model_source_authority
          BEFORE INSERT OR UPDATE OR DELETE ON model_metadata_sources
          FOR EACH ROW EXECUTE FUNCTION azents_guard_model_source_authority();
        CREATE TRIGGER guard_model_source_snapshot
          BEFORE INSERT OR UPDATE OR DELETE ON model_metadata_source_snapshots
          FOR EACH ROW EXECUTE FUNCTION azents_guard_model_source_snapshot();
        CREATE TRIGGER guard_catalog_snapshot
          BEFORE INSERT OR UPDATE ON llm_catalog_snapshots
          FOR EACH ROW EXECUTE FUNCTION azents_guard_catalog_snapshot();
        CREATE TRIGGER guard_catalog_authority
          BEFORE INSERT OR UPDATE ON llm_catalogs
          FOR EACH ROW EXECUTE FUNCTION azents_guard_catalog_authority();
        CREATE TRIGGER guard_retired_source_attempt
          BEFORE INSERT OR UPDATE ON llm_catalog_sync_attempts
          FOR EACH ROW EXECUTE FUNCTION azents_guard_retired_source_attempt()
    """)
    )


def downgrade() -> None:
    """Reject authority reversal before changing any installed guard or data."""
    raise RuntimeError(
        "This writer-contract migration is irreversible. Restore a verified "
        "matching schema/data backup with stopped producers for an emergency return."
    )
