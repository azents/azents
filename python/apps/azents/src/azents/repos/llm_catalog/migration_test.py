"""Local-only catalog cutover migration and preservation tests."""

import datetime
import json
from collections.abc import Generator
from dataclasses import dataclass
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT
from azents.core.agent import AgentModelSelection
from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogEntryVisibility,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog import ModelCapabilities
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_catalog import (
    RDBImageGenerationCatalogEntry,
    RDBLiteLLMSourceSnapshot,
    RDBLLMCatalogSyncAttempt,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.workspace import RDBWorkspace

_OLD_REVISION = "841e7188d527"
_CUTOVER_REVISION = "4550a9c9083a"
_SHADOW_REVISION = "91dd4bb71ef6"
_MAIN_REVISION = "43a0fbdc96fe"
_TABLES = (
    "workspaces",
    "llm_provider_integrations",
    "agents",
    "litellm_source_snapshots",
    "llm_catalogs",
    "llm_catalog_snapshots",
    "llm_catalog_sync_attempts",
    "llm_catalog_entries",
    "image_generation_catalog_entries",
)


@dataclass(frozen=True)
class _MigrationDatabase:
    engine: Engine
    config: AlembicConfig


@pytest.fixture
def migration_database(
    postgres_container: PostgresContainer,
) -> Generator[_MigrationDatabase, None, None]:
    """Allocate a disposable database within the isolated test container."""
    database_name = "catalog_cutover_" + uuid4().hex
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


def _assert_semantic_schema(engine: Engine, *, revision: str) -> None:
    """Check all removed dimensions and replacement uniqueness predicates."""
    inspector = sa.inspect(engine)
    catalog_columns = {
        column["name"] for column in inspector.get_columns("llm_catalogs")
    }
    entry_columns = {
        column["name"] for column in inspector.get_columns("llm_catalog_entries")
    }
    assert "lowerer_target" not in catalog_columns | entry_columns
    assert "runtime_model_identifier" not in entry_columns
    indices = {index["name"]: index for index in inspector.get_indexes("llm_catalogs")}
    system = indices["uq_llm_catalogs_system_scope_provider_purpose"]
    integration = indices["uq_llm_catalogs_integration_purpose"]
    assert system["column_names"] == ["provider", "purpose"]
    assert integration["column_names"] == ["provider_integration_id", "purpose"]
    assert system["unique"] and integration["unique"]
    assert "system" in str(system["dialect_options"]["postgresql_where"])
    assert "integration" in str(integration["dialect_options"]["postgresql_where"])
    with engine.connect() as connection:
        assert not connection.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_type "
                "WHERE typname = 'llm_catalog_lowerer_target')"
            )
        ).scalar_one()
        assert (
            connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == revision
        )


def _seed_upgrade(engine: Engine) -> str:
    """Seed real pre-cutover tables, opaque history, and shared image state."""
    with engine.begin() as connection, Session(bind=connection) as session:
        workspace = RDBWorkspace(name="Migration fixture", handle="migration-fixture")
        session.add(workspace)
        session.flush()
        integration = RDBLLMProviderIntegration(
            workspace_id=workspace.id,
            provider=LLMProvider.OPENAI,
            name="Synthetic integration",
            encrypted_credentials="synthetic-unused-credential",
            config=None,
            catalog_configuration_version=7,
        )
        session.add(integration)
        session.flush()
        for identifier, purpose in (
            ("c" * 32, "conversation"),
            ("i" * 32, "image_generation"),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO llm_catalogs "
                    "(id, scope, provider, purpose, lowerer_target, "
                    "provider_integration_id) VALUES "
                    "(:id, 'integration', 'openai', :purpose, 'litellm', :integration)"
                ),
                {"id": identifier, "purpose": purpose, "integration": integration.id},
            )
        source = RDBLiteLLMSourceSnapshot(
            id="s" * 32,
            source_key="litellm_model_cost",
            source_hash="a" * 64,
            model_count=1,
            loaded_source="remote",
            payload={
                "gpt-4o": {
                    "lowerer_target": "historical-source-evidence",
                    "input_cost_per_token": 0.00001,
                }
            },
            source_url="https://example.test/validated-source.json",
            litellm_version="1.91.3",
        )
        session.add(source)
        session.flush()
        for identifier, catalog, source_id in (
            ("p" * 32, "c" * 32, source.id),
            ("h" * 32, "c" * 32, source.id),
            ("m" * 32, "i" * 32, None),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO llm_catalog_snapshots "
                    "(id, catalog_id, entry_count, visible_count, hidden_count, "
                    "source_snapshot_id, diagnostics, catalog_configuration_version) "
                    "VALUES (:id, :catalog, 1, 1, 0, :source, "
                    "CAST(:diagnostics AS jsonb), 7)"
                ),
                {
                    "id": identifier,
                    "catalog": catalog,
                    "source": source_id,
                    "diagnostics": json.dumps({"historical": "lowerer_target"}),
                },
            )
        session.flush()
        for identifier, snapshot in (("e" * 32, "p" * 32), ("o" * 32, "h" * 32)):
            connection.execute(
                sa.text(
                    "INSERT INTO llm_catalog_entries "
                    "(id, catalog_id, snapshot_id, provider, "
                    "provider_model_identifier, "
                    "lowerer_target, runtime_model_identifier, display_name, "
                    "normalized_capabilities, "
                    "lifecycle_status, visibility_status, projection_metadata) VALUES "
                    "(:id, :catalog, :snapshot, 'openai', "
                    "'publisher/model/with/slashes', 'litellm', 'encoded/old/model', "
                    "'Semantic model', '{}'::jsonb, 'active', 'selectable', "
                    "CAST(:projection AS jsonb))"
                ),
                {
                    "id": identifier,
                    "catalog": "c" * 32,
                    "snapshot": snapshot,
                    "projection": json.dumps(
                        {
                            "lowerer_target": "litellm",
                            "runtime_model_identifier": "encoded/old/model",
                            "source_hash": source.source_hash,
                            "nested": {"lowerer_target": "opaque-nested-evidence"},
                        }
                    ),
                },
            )
        session.add(
            RDBImageGenerationCatalogEntry(
                id="g" * 32,
                catalog_id="i" * 32,
                snapshot_id="m" * 32,
                provider=LLMProvider.OPENAI,
                provider_model_identifier="gpt-image-1",
                display_name="Image fixture",
                description="Preserved image model",
                recommendation_rank=1,
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                provider_integration_id=integration.id,
                source_metadata={"image_registry": "fixture"},
                projection_metadata={"registry_revision": "fixture"},
                hidden_reason=None,
            )
        )
        for identifier, catalog in (("f" * 32, "c" * 32), ("j" * 32, "i" * 32)):
            session.add(
                RDBLLMCatalogSyncAttempt(
                    id=identifier,
                    catalog_id=catalog,
                    source_key=source.source_key,
                    status=LLMCatalogAttemptStatus.FAILED,
                    started_at=datetime.datetime.now(datetime.UTC),
                    fetched_count=0,
                    matched_count=0,
                    skipped_count=0,
                    hidden_count=0,
                    catalog_configuration_version=7,
                    failure_code="fixture_failure",
                )
            )
        historical_selection = {
            "llm_provider_integration_id": integration.id,
            "provider": "openai",
            "model_identifier": "publisher/model/with/slashes",
            "model_display_name": "Semantic model",
            "model_developer": "openai",
            "normalized_capabilities": ModelCapabilities().model_dump(mode="json"),
            "model_snapshot": {
                "lowerer_target": "litellm",
                "runtime_model_identifier": "encoded/old/model",
            },
        }
        session.add(
            RDBAgent(
                workspace_id=workspace.id,
                name="Historical selection fixture",
                model_selection=historical_selection,
                lightweight_model_selection=historical_selection,
                selectable_model_options=[{"candidates": [historical_selection]}],
                main_model_label="model",
                lightweight_model_label="model",
            )
        )
        session.flush()
        for catalog, snapshot, attempt in (
            ("c" * 32, "p" * 32, "f" * 32),
            ("i" * 32, "m" * 32, "j" * 32),
        ):
            connection.execute(
                sa.text(
                    "UPDATE llm_catalogs SET current_snapshot_id=:snapshot, "
                    "latest_attempt_id=:attempt WHERE id=:catalog"
                ),
                {"catalog": catalog, "snapshot": snapshot, "attempt": attempt},
            )
        return integration.id


def _capture_state(engine: Engine) -> dict[str, list[dict[str, object]]]:
    """Capture full row values without logging credential or native contents."""
    with engine.connect() as connection:
        return {
            table: [
                dict(row)
                for row in connection.execute(
                    sa.text(f"SELECT * FROM {table} ORDER BY id")
                ).mappings()
            ]
            for table in _TABLES
        }


def test_fresh_database_has_only_semantic_catalog_identity(
    migration_database: _MigrationDatabase,
) -> None:
    """The complete migration chain creates a descriptor-free new database."""
    command.upgrade(migration_database.config, _CUTOVER_REVISION)
    _assert_semantic_schema(migration_database.engine, revision=_CUTOVER_REVISION)


def test_fresh_database_includes_current_main_and_catalog_cutover(
    migration_database: _MigrationDatabase,
) -> None:
    """The new cutover extends current main as one linear migration chain."""
    scripts = ScriptDirectory.from_config(migration_database.config)
    assert scripts.get_heads() == [_SHADOW_REVISION]
    shadow = scripts.get_revision(_SHADOW_REVISION)
    assert shadow is not None
    assert shadow.down_revision == _CUTOVER_REVISION
    cutover = scripts.get_revision(_CUTOVER_REVISION)
    assert cutover is not None
    assert cutover.down_revision == _MAIN_REVISION
    assert all(
        isinstance(revision.down_revision, str) or revision.down_revision is None
        for revision in scripts.walk_revisions()
    )
    command.upgrade(migration_database.config, "head")
    _assert_semantic_schema(migration_database.engine, revision=_SHADOW_REVISION)
    inspector = sa.inspect(migration_database.engine)
    assert {
        "model_metadata_sources",
        "model_metadata_source_snapshots",
    }.issubset(inspector.get_table_names())
    catalog_columns = {
        column["name"] for column in inspector.get_columns("llm_catalogs")
    }
    snapshot_columns = {
        column["name"] for column in inspector.get_columns("llm_catalog_snapshots")
    }
    assert "rollback_snapshot_id" in catalog_columns
    assert {
        "metadata_source_snapshot_id",
        "projection_schema_version",
        "runtime_profile_resolver_revision",
        "pydantic_ai_version",
        "genai_prices_version",
        "projection_fingerprint",
    }.issubset(snapshot_columns)


@pytest.mark.parametrize("starting_revision", [_OLD_REVISION, _MAIN_REVISION])
def test_upgrade_preserves_state_and_cleans_only_active_projection_keys(
    migration_database: _MigrationDatabase,
    monkeypatch: pytest.MonkeyPatch,
    starting_revision: str,
) -> None:
    """Existing selections, snapshots and image state survive without remote fetch."""
    command.upgrade(migration_database.config, starting_revision)
    _seed_upgrade(migration_database.engine)
    before = _capture_state(migration_database.engine)

    # No source/provider client is allowed during the database transition.
    def forbidden_remote(*args: object, **kwargs: object) -> None:
        raise AssertionError("Migration must not fetch remote source/provider data")

    monkeypatch.setattr("httpx.AsyncClient.request", forbidden_remote)
    monkeypatch.setattr("httpx.Client.request", forbidden_remote)
    command.upgrade(migration_database.config, _CUTOVER_REVISION)
    _assert_semantic_schema(migration_database.engine, revision=_CUTOVER_REVISION)
    expected = before
    for row in expected["llm_catalogs"]:
        row.pop("lowerer_target")
    for row in expected["llm_catalog_entries"]:
        row.pop("lowerer_target")
        row.pop("runtime_model_identifier")
        if row["id"] == "e" * 32:
            projection = row["projection_metadata"]
            assert isinstance(projection, dict)
            projection.pop("lowerer_target")
            projection.pop("runtime_model_identifier")
    assert _capture_state(migration_database.engine) == expected
    selection = expected["agents"][0]["model_selection"]
    restored_selection = AgentModelSelection.model_validate(selection)
    assert restored_selection.model_identifier == "publisher/model/with/slashes"
    assert restored_selection.model_snapshot["lowerer_target"] == "litellm"
    with pytest.raises(RuntimeError, match="irreversible"):
        command.downgrade(migration_database.config, _OLD_REVISION)
    assert _capture_state(migration_database.engine) == expected


@pytest.mark.parametrize("scope", ["system", "integration"])
def test_semantic_identity_collisions_abort_before_any_transition(
    migration_database: _MigrationDatabase,
    scope: str,
) -> None:
    """Bounded preflight fails without deleting or merging unexpected catalogs."""
    command.upgrade(migration_database.config, _MAIN_REVISION)
    integration_id = _seed_upgrade(migration_database.engine)
    with migration_database.engine.begin() as connection:
        if scope == "integration":
            old_index = "uq_llm_catalogs_integration_target_purpose"
        else:
            old_index = "uq_llm_catalogs_system_scope_provider_target_purpose"
        connection.execute(sa.text(f"DROP INDEX {old_index}"))
        for _ in range(7):
            connection.execute(
                sa.text(
                    "INSERT INTO llm_catalogs "
                    "(id, scope, provider, purpose, lowerer_target, "
                    "provider_integration_id) VALUES "
                    "(:id, :scope, 'openai', 'conversation', 'litellm', :integration)"
                ),
                {
                    "id": uuid4().hex,
                    "scope": scope,
                    "integration": integration_id if scope == "integration" else None,
                },
            )
    before = _capture_state(migration_database.engine)
    with pytest.raises(RuntimeError, match="semantic identity collisions") as failure:
        command.upgrade(migration_database.config, _CUTOVER_REVISION)
    assert len(str(failure.value)) < 1024
    assert "no catalogs were merged or deleted" in str(failure.value)
    assert _capture_state(migration_database.engine) == before
    with migration_database.engine.connect() as connection:
        assert (
            connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == _MAIN_REVISION
        )
    assert "lowerer_target" in {
        column["name"]
        for column in sa.inspect(migration_database.engine).get_columns("llm_catalogs")
    }
