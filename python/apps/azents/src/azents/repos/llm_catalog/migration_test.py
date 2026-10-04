"""Model metadata cleanup migration tests."""

from collections.abc import Generator
from dataclasses import dataclass
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import ProgrammingError
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_SHADOW_REVISION = "91dd4bb71ef6"
_CLEANUP_REVISION = "d29225579621"
_NAMESPACE_REVISION = "af654664e6b6"
_RECONCILIATION_REVISION = "a0dac2fe3ca2"
_TOOLKIT_REVISION = "cda14157c46c"
_HISTORICAL_MEMORY_REVISION = "459a4285993c"
_DATA_SOURCE_CUTOVER_REVISION = "c8bc0a5dcab0"
_SCHEMA_ALIGNMENT_REVISION = "1c42cc5ce89f"
_CURRENT_DATA_REVISION = "d9bff320245f"


@dataclass(frozen=True)
class _MigrationDatabase:
    engine: Engine
    config: AlembicConfig


@pytest.fixture
def migration_database(
    postgres_container: PostgresContainer,
) -> Generator[_MigrationDatabase, None, None]:
    """Allocate a disposable database within the isolated test container."""
    database_name = "catalog_cleanup_" + uuid4().hex
    admin = sa.create_engine(
        postgres_container.get_connection_url(), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as connection:
        connection.execute(sa.text(f"CREATE DATABASE {database_name}"))
    url = sa.engine.make_url(postgres_container.get_connection_url()).set(
        database=database_name
    )
    config = AlembicConfig(PROJECT_ROOT / "db-schemas/rdb/alembic.ini")
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    engine = sa.create_engine(url)
    try:
        yield _MigrationDatabase(engine=engine, config=config)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(sa.text(f"DROP DATABASE {database_name} WITH (FORCE)"))
        admin.dispose()


def _assert_cleanup_schema(engine: Engine) -> None:
    inspector = sa.inspect(engine)
    assert "litellm_source_snapshots" not in inspector.get_table_names()
    catalog_columns = {
        column["name"] for column in inspector.get_columns("llm_catalogs")
    }
    snapshot_columns = {
        column["name"] for column in inspector.get_columns("llm_catalog_snapshots")
    }
    assert "rollback_snapshot_id" not in catalog_columns
    assert "metadata_source_snapshot_id" not in snapshot_columns
    assert "source_snapshot_id" in snapshot_columns
    indexes = {
        index["name"]: index for index in inspector.get_indexes("llm_catalog_snapshots")
    }
    assert indexes["ix_llm_catalog_snapshots_source_snapshot_id"]["column_names"] == [
        "source_snapshot_id"
    ]


def _assert_revision(engine: Engine, revision: str) -> None:
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == revision
        )


def _assert_upgrade_rejected(
    migration_database: _MigrationDatabase,
    *,
    message: str,
) -> None:
    with pytest.raises(ProgrammingError) as failure:
        command.upgrade(migration_database.config, _CLEANUP_REVISION)
    assert message in str(failure.value.orig)


def _seed_ready_cutover(engine: Engine) -> None:
    """Seed generic current state plus removable legacy rollback evidence."""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO model_metadata_sources "
                "(source_key, current_snapshot_id, latest_attempt_id) "
                "VALUES ('genai_prices', :source, NULL)"
            ),
            {"source": "g" * 32},
        )
        connection.execute(
            sa.text(
                "INSERT INTO model_metadata_source_snapshots "
                "(id, source_key, source_kind, source_schema_version, source_url, "
                "source_hash, producer_name, producer_version, provider_count, "
                "model_count, payload) VALUES "
                "(:id, 'genai_prices', 'genai_prices', '1', "
                "'https://metadata.example/source.json', :hash, 'genai-prices', "
                "'0.1.9', 1, 1, '{\"providers\": []}'::jsonb)"
            ),
            {"id": "g" * 32, "hash": "g" * 64},
        )
        connection.execute(
            sa.text(
                "INSERT INTO litellm_source_snapshots "
                "(id, source_key, source_hash, model_count, loaded_source, payload) "
                "VALUES (:id, 'litellm_model_cost', :hash, 1, 'remote', '{}'::jsonb)"
            ),
            {"id": "l" * 32, "hash": "l" * 64},
        )
        connection.execute(
            sa.text(
                "INSERT INTO llm_catalogs "
                "(id, scope, provider, purpose, current_snapshot_id, "
                "rollback_snapshot_id, latest_attempt_id) VALUES "
                "(:id, 'system', 'openai', 'conversation', :current, :rollback, NULL)"
            ),
            {"id": "c" * 32, "current": "n" * 32, "rollback": "o" * 32},
        )
        connection.execute(
            sa.text(
                "INSERT INTO llm_catalog_snapshots "
                "(id, catalog_id, entry_count, visible_count, hidden_count, "
                "source_snapshot_id, metadata_source_snapshot_id, "
                "projection_schema_version, runtime_profile_resolver_revision, "
                "pydantic_ai_version, genai_prices_version, projection_fingerprint) "
                "VALUES (:legacy, :catalog, 0, 0, 0, :old_source, NULL, NULL, NULL, "
                "NULL, NULL, NULL), (:current, :catalog, 0, 0, 0, NULL, :source, "
                "'1', '1', '2.52.0', '0.1.9', :fingerprint)"
            ),
            {
                "legacy": "o" * 32,
                "current": "n" * 32,
                "catalog": "c" * 32,
                "old_source": "l" * 32,
                "source": "g" * 32,
                "fingerprint": "f" * 64,
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO llm_catalog_sync_attempts "
                "(id, catalog_id, source_key, status, started_at, fetched_count, "
                "matched_count, skipped_count, hidden_count) VALUES "
                "(:legacy, :catalog, 'litellm_model_cost', 'succeeded', now(), "
                "1, 1, 0, 0), "
                "(:generic, :catalog, 'genai_prices', 'succeeded', "
                "now() - interval '1 second', 1, 1, 0, 0)"
            ),
            {
                "legacy": "a" * 32,
                "generic": "b" * 32,
                "catalog": "c" * 32,
            },
        )
        connection.execute(
            sa.text(
                "UPDATE llm_catalogs SET latest_attempt_id = :attempt WHERE id = :id"
            ),
            {"attempt": "a" * 32, "id": "c" * 32},
        )
        connection.execute(
            sa.text(
                "INSERT INTO scheduled_task_states (task_key, next_run_at) VALUES "
                "('model_catalog_integration_reprojection', now()), "
                "('model_metadata_shadow_projection', now())"
            )
        )


def test_fresh_upgrade_has_only_generic_source_schema(
    migration_database: _MigrationDatabase,
) -> None:
    """A fresh database reaches the current linear head without legacy objects."""
    scripts = ScriptDirectory.from_config(migration_database.config)
    current = scripts.get_revision(_CURRENT_DATA_REVISION)
    assert current is not None
    assert current.down_revision == _SCHEMA_ALIGNMENT_REVISION
    current_revision = (PROJECT_ROOT / "db-schemas/rdb/revision").read_text().strip()
    assert scripts.get_heads() == [current_revision]
    head = scripts.get_revision(_SCHEMA_ALIGNMENT_REVISION)
    assert head is not None
    assert head.down_revision == _DATA_SOURCE_CUTOVER_REVISION
    cutover = scripts.get_revision(_DATA_SOURCE_CUTOVER_REVISION)
    assert cutover is not None
    assert cutover.down_revision == _HISTORICAL_MEMORY_REVISION
    historical_memory = scripts.get_revision(_HISTORICAL_MEMORY_REVISION)
    assert historical_memory is not None
    assert historical_memory.down_revision == _TOOLKIT_REVISION
    toolkit = scripts.get_revision(_TOOLKIT_REVISION)
    assert toolkit is not None
    assert toolkit.down_revision == _RECONCILIATION_REVISION
    reconciliation = scripts.get_revision(_RECONCILIATION_REVISION)
    assert reconciliation is not None
    assert reconciliation.down_revision == _NAMESPACE_REVISION
    namespace = scripts.get_revision(_NAMESPACE_REVISION)
    assert namespace is not None
    assert namespace.down_revision == _CLEANUP_REVISION
    command.upgrade(migration_database.config, _SCHEMA_ALIGNMENT_REVISION)
    _assert_revision(migration_database.engine, _SCHEMA_ALIGNMENT_REVISION)
    _assert_cleanup_schema(migration_database.engine)


def test_historical_memory_revision_extends_toolkit_head(
    migration_database: _MigrationDatabase,
) -> None:
    """Historical Memory preserves the complete canonical Toolkit chain."""
    scripts = ScriptDirectory.from_config(migration_database.config)
    current = scripts.get_revision(_CURRENT_DATA_REVISION)
    assert current is not None
    assert current.down_revision == _SCHEMA_ALIGNMENT_REVISION
    current_revision = (
        (PROJECT_ROOT / "db-schemas" / "rdb" / "revision").read_text().strip()
    )
    assert scripts.get_heads() == [current_revision]
    head = scripts.get_revision(_SCHEMA_ALIGNMENT_REVISION)
    assert head is not None
    assert head.down_revision == _DATA_SOURCE_CUTOVER_REVISION
    cutover = scripts.get_revision(_DATA_SOURCE_CUTOVER_REVISION)
    assert cutover is not None
    assert cutover.down_revision == _HISTORICAL_MEMORY_REVISION
    historical_memory = scripts.get_revision(_HISTORICAL_MEMORY_REVISION)
    assert historical_memory is not None
    assert historical_memory.down_revision == _TOOLKIT_REVISION


def test_ready_cutover_upgrade_removes_legacy_state_and_preserves_current(
    migration_database: _MigrationDatabase,
) -> None:
    """A Phase 2-ready database keeps generic current state during cleanup."""
    command.upgrade(migration_database.config, _SHADOW_REVISION)
    _seed_ready_cutover(migration_database.engine)
    command.upgrade(migration_database.config, _CLEANUP_REVISION)
    _assert_cleanup_schema(migration_database.engine)
    with migration_database.engine.connect() as connection:
        catalog = connection.execute(
            sa.text(
                "SELECT current_snapshot_id, latest_attempt_id "
                "FROM llm_catalogs WHERE id = :catalog"
            ),
            {"catalog": "c" * 32},
        ).one()
        source = connection.execute(
            sa.text(
                "SELECT source_snapshot_id FROM llm_catalog_snapshots WHERE id = :id"
            ),
            {"id": "n" * 32},
        ).scalar_one()
        legacy_attempts = connection.execute(
            sa.text(
                "SELECT count(*) FROM llm_catalog_sync_attempts "
                "WHERE source_key = 'litellm_model_cost'"
            )
        ).scalar_one()
        retired_task_states = connection.execute(
            sa.text(
                "SELECT count(*) FROM scheduled_task_states WHERE task_key IN "
                "('model_catalog_integration_reprojection', "
                "'model_metadata_shadow_projection')"
            )
        ).scalar_one()
    assert catalog.current_snapshot_id == "n" * 32
    assert catalog.latest_attempt_id == "b" * 32
    assert source == "g" * 32
    assert legacy_attempts == 0
    assert retired_task_states == 0


def test_cleanup_rejects_running_catalog_attempt(
    migration_database: _MigrationDatabase,
) -> None:
    """Cleanup leaves the Phase 2 schema intact while an attempt is running."""
    command.upgrade(migration_database.config, _SHADOW_REVISION)
    with migration_database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO llm_catalog_sync_attempts "
                "(id, catalog_id, source_key, status, started_at, fetched_count, "
                "matched_count, skipped_count, hidden_count) VALUES "
                "(:id, NULL, 'genai_prices', 'running', now(), 0, 0, 0, 0)"
            ),
            {"id": "r" * 32},
        )

    _assert_upgrade_rejected(
        migration_database,
        message="catalog attempts are still running",
    )

    _assert_revision(migration_database.engine, _SHADOW_REVISION)
    assert (
        "litellm_source_snapshots"
        in sa.inspect(migration_database.engine).get_table_names()
    )


def test_cleanup_allows_conversation_catalog_without_current_snapshot(
    migration_database: _MigrationDatabase,
) -> None:
    """An unsynchronized catalog has no legacy current authority to migrate."""
    command.upgrade(migration_database.config, _SHADOW_REVISION)
    with migration_database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO workspaces (id, name, handle) "
                "VALUES (:id, 'Migration Workspace', 'migration-workspace')"
            ),
            {"id": "w" * 32},
        )
        connection.execute(
            sa.text(
                "INSERT INTO llm_provider_integrations "
                "(id, workspace_id, provider, name, encrypted_credentials, "
                "config, enabled) VALUES "
                "(:id, :workspace, 'chatgpt_oauth', 'ChatGPT', "
                "'encrypted-placeholder', NULL, true)"
            ),
            {"id": "i" * 32, "workspace": "w" * 32},
        )
        connection.execute(
            sa.text(
                "INSERT INTO llm_catalogs "
                "(id, scope, provider, purpose, provider_integration_id) VALUES "
                "(:id, 'integration', 'chatgpt_oauth', 'conversation', :integration)"
            ),
            {"id": "c" * 32, "integration": "i" * 32},
        )

    command.upgrade(migration_database.config, _CLEANUP_REVISION)

    _assert_cleanup_schema(migration_database.engine)


def test_cleanup_allows_system_catalog_without_current_snapshot(
    migration_database: _MigrationDatabase,
) -> None:
    """A missing system current pin can be rebuilt from generic metadata."""
    command.upgrade(migration_database.config, _SHADOW_REVISION)
    with migration_database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO llm_catalogs "
                "(id, scope, provider, purpose) VALUES "
                "(:id, 'system', 'openai', 'conversation')"
            ),
            {"id": "c" * 32},
        )

    command.upgrade(migration_database.config, _CLEANUP_REVISION)

    _assert_cleanup_schema(migration_database.engine)
    with migration_database.engine.connect() as connection:
        current_snapshot_id = connection.execute(
            sa.text("SELECT current_snapshot_id FROM llm_catalogs WHERE id = :catalog"),
            {"catalog": "c" * 32},
        ).scalar_one()
    assert current_snapshot_id is None


def test_cleanup_clears_current_conversation_catalog_without_generic_provenance(
    migration_database: _MigrationDatabase,
) -> None:
    """Cleanup clears a stale current pin so generic projection can rebuild it."""
    command.upgrade(migration_database.config, _SHADOW_REVISION)
    _seed_ready_cutover(migration_database.engine)
    with migration_database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE llm_catalogs SET current_snapshot_id = rollback_snapshot_id "
                "WHERE id = :id"
            ),
            {"id": "c" * 32},
        )

    command.upgrade(migration_database.config, _CLEANUP_REVISION)

    _assert_cleanup_schema(migration_database.engine)
    with migration_database.engine.connect() as connection:
        catalog = connection.execute(
            sa.text("SELECT current_snapshot_id FROM llm_catalogs WHERE id = :catalog"),
            {"catalog": "c" * 32},
        ).scalar_one()
        stale_snapshot_count = connection.execute(
            sa.text("SELECT count(*) FROM llm_catalog_snapshots WHERE id = :snapshot"),
            {"snapshot": "o" * 32},
        ).scalar_one()
    assert catalog is None
    assert stale_snapshot_count == 0


def test_cleanup_rejects_missing_generic_source_authority(
    migration_database: _MigrationDatabase,
) -> None:
    """Current generic catalogs require the matching runtime source pointer."""
    command.upgrade(migration_database.config, _SHADOW_REVISION)
    _seed_ready_cutover(migration_database.engine)
    with migration_database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE model_metadata_sources SET current_snapshot_id = NULL "
                "WHERE source_key = 'genai_prices'"
            )
        )

    _assert_upgrade_rejected(
        migration_database,
        message="generic model metadata source is unavailable",
    )

    _assert_revision(migration_database.engine, _SHADOW_REVISION)


def test_cleanup_clears_legacy_metadata_in_current_generic_entry(
    migration_database: _MigrationDatabase,
) -> None:
    """A contaminated generic snapshot is unpinned and deleted for rebuilding."""
    command.upgrade(migration_database.config, _SHADOW_REVISION)
    _seed_ready_cutover(migration_database.engine)
    with migration_database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO llm_catalog_entries "
                "(id, catalog_id, snapshot_id, provider, "
                "provider_model_identifier, display_name, normalized_capabilities, "
                "lifecycle_status, visibility_status, source_metadata, "
                "projection_metadata) VALUES "
                "(:id, :catalog, :snapshot, 'xai', 'grok-test', 'Grok Test', "
                "'{}'::jsonb, 'active', 'selectable', "
                '\'{"provider_metadata": {"litellm_provider": "xai"}}\'::jsonb, '
                "'{\"matched\": true}'::jsonb)"
            ),
            {
                "id": "e" * 32,
                "catalog": "c" * 32,
                "snapshot": "n" * 32,
            },
        )

    executed_statements: list[str] = []

    def capture_statement(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        executed_statements.append(statement)

    event.listen(
        Engine,
        "before_cursor_execute",
        capture_statement,
    )
    try:
        command.upgrade(migration_database.config, _CLEANUP_REVISION)
    finally:
        event.remove(
            Engine,
            "before_cursor_execute",
            capture_statement,
        )

    _assert_cleanup_schema(migration_database.engine)
    with migration_database.engine.connect() as connection:
        catalog = connection.execute(
            sa.text("SELECT current_snapshot_id FROM llm_catalogs WHERE id = :catalog"),
            {"catalog": "c" * 32},
        ).scalar_one()
        contaminated_snapshot_count = connection.execute(
            sa.text("SELECT count(*) FROM llm_catalog_snapshots WHERE id = :snapshot"),
            {"snapshot": "n" * 32},
        ).scalar_one()
    assert catalog is None
    assert contaminated_snapshot_count == 0
    constraint_flush_index = next(
        index
        for index, statement in enumerate(executed_statements)
        if "SET CONSTRAINTS ALL IMMEDIATE" in statement
    )
    catalog_ddl_index = next(
        index
        for index, statement in enumerate(executed_statements)
        if "ALTER TABLE llm_catalogs DROP COLUMN rollback_snapshot_id" in statement
    )
    assert constraint_flush_index < catalog_ddl_index


def test_cleanup_rejects_invalid_rollback_pin(
    migration_database: _MigrationDatabase,
) -> None:
    """Cleanup does not delete a pin that cannot represent pre-cutover state."""
    command.upgrade(migration_database.config, _SHADOW_REVISION)
    _seed_ready_cutover(migration_database.engine)
    with migration_database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE llm_catalogs SET rollback_snapshot_id = current_snapshot_id "
                "WHERE id = :id"
            ),
            {"id": "c" * 32},
        )

    _assert_upgrade_rejected(
        migration_database,
        message="rollback pins are not valid pre-cutover snapshots",
    )

    _assert_revision(migration_database.engine, _SHADOW_REVISION)


def test_cleanup_downgrade_is_explicitly_irreversible(
    migration_database: _MigrationDatabase,
) -> None:
    """Deleted legacy authority cannot be reconstructed by application downgrade."""
    command.upgrade(migration_database.config, _CLEANUP_REVISION)

    with pytest.raises(RuntimeError, match="irreversible"):
        command.downgrade(migration_database.config, _SHADOW_REVISION)

    _assert_revision(migration_database.engine, _CLEANUP_REVISION)
    _assert_cleanup_schema(migration_database.engine)
