"""Dedicated-database regressions for lossless source-kind schema alignment."""

import pytest
import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

_BEFORE_GUARDS = "459a4285993c"
_PARENT = "c8bc0a5dcab0"
_REVISION = "1c42cc5ce89f"


def _seed_historical_source(engine: Engine, *, kind: str) -> None:
    """Create retained old-source evidence before its writer guard is installed."""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO model_metadata_sources (source_key) "
                "VALUES ('genai_prices') ON CONFLICT (source_key) DO NOTHING"
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO model_metadata_source_snapshots (
                  id, source_key, source_kind, source_schema_version, source_url,
                  source_hash, producer_name, producer_version,
                  provider_count, model_count, payload
                ) VALUES (
                  repeat('1', 32), 'genai_prices', :kind, 'historical-schema',
                  'https://example.test/historical-source', repeat('a', 64),
                  'Historical producer', 'historical-version', 0, 0,
                  '{"historical_evidence":"retain exactly"}'::jsonb
                )
                """
            ),
            {"kind": kind},
        )


def test_alignment_preserves_retired_and_active_snapshot_evidence(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Both source contracts retain IDs, payloads, counts and writer guards."""
    alembic_runner.migrate_up_to(_BEFORE_GUARDS)
    _seed_historical_source(alembic_engine, kind="genai_prices")
    alembic_runner.migrate_up_to(_PARENT)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO model_metadata_source_snapshots (
                  id, source_key, source_kind, source_schema_version, source_url,
                  source_hash, producer_name, producer_version,
                  provider_count, model_count, payload
                ) VALUES (
                  repeat('2', 32), 'litellm_catalog', 'litellm_json', '1',
                  'https://example.test/active-source', repeat('b', 64),
                  'Active producer', 'active-version', 0, 0,
                  '{"candidate_evidence":"retain exactly"}'::jsonb
                )
                """
            )
        )
        before = connection.execute(
            sa.text(
                "SELECT id, source_key, source_kind::text, source_schema_version, "
                "source_hash, provider_count, model_count, payload, created_at "
                "FROM model_metadata_source_snapshots ORDER BY id"
            )
        ).all()
    alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.connect() as connection:
        after = connection.execute(
            sa.text(
                "SELECT id, source_key, source_kind::text, source_schema_version, "
                "source_hash, provider_count, model_count, payload, created_at "
                "FROM model_metadata_source_snapshots ORDER BY id"
            )
        ).all()
        assert after == before
        assert (
            connection.scalar(
                sa.text(
                    "SELECT pg_typeof(source_kind)::text "
                    "FROM model_metadata_source_snapshots LIMIT 1"
                )
            )
            == "model_metadata_source_kind"
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT to_regclass('ix_llm_catalogs_provider_purpose') IS NOT NULL"
                )
            )
            is True
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT to_regclass("
                    "'ix_image_generation_catalog_entries_catalog_rank') IS NOT NULL"
                )
            )
            is True
        )
    with pytest.raises(DBAPIError, match="Retired model source snapshots"):
        with alembic_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE model_metadata_source_snapshots "
                    "SET producer_version = 'must-not-change' "
                    "WHERE id = repeat('1', 32)"
                )
            )


def test_alignment_rejects_unknown_historical_kind_before_enum_creation(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Unsupported retained rows stop conversion without deletion or coercion."""
    alembic_runner.migrate_up_to(_BEFORE_GUARDS)
    _seed_historical_source(alembic_engine, kind="unreviewed-kind")
    alembic_runner.migrate_up_to(_PARENT)
    with pytest.raises(DBAPIError, match="unsupported source contract"):
        alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text(
                    "SELECT source_kind FROM model_metadata_source_snapshots "
                    "WHERE id = repeat('1', 32)"
                )
            )
            == "unreviewed-kind"
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM pg_type "
                    "WHERE typname = 'model_metadata_source_kind')"
                )
            )
            is False
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT to_regclass("
                    "'ix_model_metadata_source_snapshots_source_created') IS NOT NULL"
                )
            )
            is True
        )


def test_alignment_requires_enabled_cutover_guards(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """A disabled predecessor guard is a preflight failure, not migration authority."""
    alembic_runner.migrate_up_to(_PARENT)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                "ALTER TABLE model_metadata_source_snapshots "
                "DISABLE TRIGGER guard_model_source_snapshot"
            )
        )
    with pytest.raises(DBAPIError, match="installed cutover guards"):
        alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM pg_type "
                    "WHERE typname = 'model_metadata_source_kind')"
                )
            )
            is False
        )
