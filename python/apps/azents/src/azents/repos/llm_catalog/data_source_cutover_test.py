"""Disposable PostgreSQL coverage for the data-only source writer cutover."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4

import httpx
import psycopg
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT
from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    CATALOG_SOURCE_SCHEMA_VERSION,
    decode_catalog_source,
)

_PARENT = "459a4285993c"
_CUTOVER = "c8bc0a5dcab0"
_OLD_SOURCE = "s" * 32
_OLD_UNUSED_SOURCE = "u" * 32
_OLD_SNAPSHOT = "o" * 32
_CATALOG = "c" * 32
_NEW_SOURCE = "n" * 32
_NEW_SNAPSHOT = "p" * 32
_WORKSPACE = "w" * 32
_INTEGRATION = "i" * 32
_OLD_ATTEMPT = "a" * 32


@dataclass(frozen=True)
class _Database:
    engine: Engine
    config: AlembicConfig


@contextmanager
def _rejected(engine: Engine) -> Generator[Connection]:
    """Require an admission/FK error, not unrelated malformed test SQL."""
    with pytest.raises(DBAPIError) as failure, engine.begin() as connection:
        yield connection
    assert isinstance(failure.value.orig, psycopg.Error)
    assert failure.value.orig.sqlstate in {"P0001", "23503", "23514"}


@pytest.fixture
def database(postgres_container: PostgresContainer) -> Generator[_Database]:
    """Create and discard a distinct database, never an application database."""
    name = "catalog_data_cutover_" + uuid4().hex
    admin = sa.create_engine(
        postgres_container.get_connection_url(), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as connection:
        connection.execute(sa.text(f"CREATE DATABASE {name}"))
    url = sa.engine.make_url(postgres_container.get_connection_url()).set(database=name)
    config = AlembicConfig(PROJECT_ROOT / "db-schemas/rdb/alembic.ini")
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    engine = sa.create_engine(url)
    try:
        command.upgrade(config, _PARENT)
        _seed_old_only(engine)
        yield _Database(engine=engine, config=config)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(sa.text(f"DROP DATABASE {name} WITH (FORCE)"))
        admin.dispose()


@pytest.fixture
def cutover(database: _Database) -> _Database:
    """Apply the SQL-only cutover to valid historical rows."""
    command.upgrade(database.config, _CUTOVER)
    return database


def _source(
    connection: Connection,
    *,
    snapshot_id: str,
    source_key: str,
    source_kind: str,
    schema: str,
    payload: str,
    content_hash: str,
) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO model_metadata_source_snapshots "
            "(id, source_key, source_kind, source_schema_version, source_url, "
            "source_hash, producer_name, producer_version, provider_count, "
            "model_count, payload) VALUES "
            "(:id, :key, :kind, :schema, 'https://metadata.example/data.json', "
            ":hash, 'fixture', '1', 1, 1, CAST(:payload AS jsonb))"
        ),
        {
            "id": snapshot_id,
            "key": source_key,
            "kind": source_kind,
            "schema": schema,
            "hash": content_hash,
            "payload": payload,
        },
    )


def _catalog(
    connection: Connection,
    *,
    catalog_id: str,
    scope: str,
    purpose: str,
    integration_id: str | None,
    provider: str,
) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO llm_catalogs "
            "(id, scope, provider, purpose, provider_integration_id) "
            "VALUES (:id, :scope, :provider, :purpose, :integration)"
        ),
        {
            "id": catalog_id,
            "scope": scope,
            "purpose": purpose,
            "integration": integration_id,
            "provider": provider,
        },
    )


def _snapshot(
    connection: Connection,
    *,
    snapshot_id: str,
    catalog_id: str,
    source_id: str | None,
    schema: str | None,
    genai_version: str | None,
) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO llm_catalog_snapshots "
            "(id, catalog_id, entry_count, visible_count, hidden_count, "
            "source_snapshot_id, projection_schema_version, "
            "runtime_profile_resolver_revision, genai_prices_version, "
            "projection_fingerprint) VALUES "
            "(:id, :catalog, 1, 1, 0, :source, :schema, 'fixture', :genai, :hash)"
        ),
        {
            "id": snapshot_id,
            "catalog": catalog_id,
            "source": source_id,
            "schema": schema,
            "genai": genai_version,
            "hash": snapshot_id * 2,
        },
    )


def _seed_old_only(engine: Engine) -> None:
    """Use SQL historical shapes without decoding the retired payload."""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO model_metadata_sources (source_key) "
                "VALUES ('genai_prices')"
            )
        )
        for snapshot_id in (_OLD_SOURCE, _OLD_UNUSED_SOURCE):
            _source(
                connection,
                snapshot_id=snapshot_id,
                source_key="genai_prices",
                source_kind="genai_prices",
                schema="1",
                payload='{"retired_opaque_history":"not a new decoder payload"}',
                content_hash=snapshot_id * 2,
            )
        connection.execute(
            sa.text(
                "UPDATE model_metadata_sources SET current_snapshot_id=:source "
                "WHERE source_key='genai_prices'"
            ),
            {"source": _OLD_SOURCE},
        )
        _catalog(
            connection,
            catalog_id=_CATALOG,
            scope="system",
            purpose="conversation",
            integration_id=None,
            provider="openai",
        )
        _snapshot(
            connection,
            snapshot_id=_OLD_SNAPSHOT,
            catalog_id=_CATALOG,
            source_id=_OLD_SOURCE,
            schema="1",
            genai_version="historical",
        )
        connection.execute(
            sa.text(
                "UPDATE llm_catalogs SET current_snapshot_id=:snapshot WHERE id=:id"
            ),
            {"snapshot": _OLD_SNAPSHOT, "id": _CATALOG},
        )
        connection.execute(
            sa.text(
                "INSERT INTO llm_catalog_entries "
                "(id, catalog_id, snapshot_id, provider, provider_model_identifier, "
                "display_name, normalized_capabilities, supported_execution_options, "
                "lifecycle_status, visibility_status) VALUES "
                "(:id, :catalog, :snapshot, 'openai', 'gpt-historical', 'Historical', "
                '\'{"built_in_tools":{"supported":["web_search"]}}\'::jsonb, '
                "'[]'::jsonb, 'active', 'selectable')"
            ),
            {"id": "e" * 32, "catalog": _CATALOG, "snapshot": _OLD_SNAPSHOT},
        )
        connection.execute(
            sa.text(
                "INSERT INTO llm_catalog_sync_attempts "
                "(id, catalog_id, source_key, status, started_at, fetched_count, "
                "matched_count, skipped_count, hidden_count) "
                "VALUES (:id, NULL, 'genai_prices', 'running', now(), 0, 0, 0, 0)"
            ),
            {"id": _OLD_ATTEMPT},
        )
        connection.execute(
            sa.text(
                "UPDATE model_metadata_sources SET latest_attempt_id=:id "
                "WHERE source_key='genai_prices'"
            ),
            {"id": _OLD_ATTEMPT},
        )
        _seed_saved_history(connection)


def _seed_saved_history(connection: Connection) -> None:
    """Keep actual saved-selection and recorded event tables in the matrix."""
    selection = json.dumps(
        {
            "provider": "openai",
            "model_identifier": "gpt-historical",
            "model_display_name": "Historical",
            "model_developer": "openai",
            "normalized_capabilities": {
                "built_in_tools": {"supported": ["web_search"]}
            },
            "model_snapshot": {},
        }
    )
    options = json.dumps(
        [
            {
                "label": "Main",
                "candidates": [
                    {
                        "model_selection": json.loads(selection),
                        "settings": {"builtin_tools": []},
                    }
                ],
            }
        ]
    )
    connection.execute(
        sa.text(
            "INSERT INTO workspaces (id, name, handle) "
            "VALUES (:id, 'Cutover history', 'cutover-history')"
        ),
        {"id": _WORKSPACE},
    )
    connection.execute(
        sa.text(
            "INSERT INTO agents "
            "(id, workspace_id, name, model_selection, lightweight_model_selection, "
            "selectable_model_options, main_model_label, lightweight_model_label, "
            "enabled, type, memory_enabled) VALUES "
            "(:id, :workspace, 'Historical', CAST(:selection AS jsonb), "
            "CAST(:selection AS jsonb), CAST(:options AS jsonb), 'Main', 'Main', "
            "true, 'public', true)"
        ),
        {
            "id": "g" * 32,
            "workspace": _WORKSPACE,
            "selection": selection,
            "options": options,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO workspace_model_settings "
            "(workspace_id, default_model_selection, "
            "default_lightweight_model_selection) "
            "VALUES (:workspace, CAST(:selection AS jsonb), CAST(:selection AS jsonb))"
        ),
        {"workspace": _WORKSPACE, "selection": selection},
    )
    connection.execute(
        sa.text(
            "INSERT INTO agent_sessions "
            "(id, workspace_id, agent_id, handle, session_kind, status, "
            "start_reason, product_mode, primary_kind) "
            "VALUES (:id, :workspace, :agent, 'history', 'root', 'active', "
            "'initial', 'team', 'team_primary')"
        ),
        {"id": "h" * 32, "workspace": _WORKSPACE, "agent": "g" * 32},
    )
    connection.execute(
        sa.text(
            "INSERT INTO events (id, session_id, kind, payload) "
            "VALUES (:id, :session, 'assistant_message', "
            '\'{"content":"Historical","usage":{"estimated_cost":'
            '{"total_usd":"0.012","source_key":"genai_prices"}}}\'::jsonb)'
        ),
        {"id": "v" * 32, "session": "h" * 32},
    )
    connection.execute(
        sa.text(
            "INSERT INTO llm_provider_integrations "
            "(id, workspace_id, provider, name, encrypted_credentials, "
            "config, enabled) "
            "VALUES (:id, :workspace, 'openai', 'Fixture', "
            "'inert-test-row', NULL, true)"
        ),
        {"id": _INTEGRATION, "workspace": _WORKSPACE},
    )


def _new_source(connection: Connection, *, snapshot_id: str) -> None:
    """Fixture creation may use the strict helper; the migration must not."""
    payload = decode_catalog_source(
        json.dumps(
            {
                "gpt-fixture-" + snapshot_id[0]: {
                    "litellm_provider": "openai",
                    "mode": "chat",
                }
            }
        ).encode()
    )
    _source(
        connection,
        snapshot_id=snapshot_id,
        source_key=CATALOG_SOURCE_KEY,
        source_kind=CATALOG_SOURCE_KIND,
        schema=CATALOG_SOURCE_SCHEMA_VERSION,
        payload=payload.model_dump_json(),
        content_hash=payload.content_hash,
    )
    connection.execute(
        sa.text(
            "UPDATE model_metadata_sources SET current_snapshot_id=:source "
            "WHERE source_key=:key"
        ),
        {"source": snapshot_id, "key": CATALOG_SOURCE_KEY},
    )


def _preserved_rows(engine: Engine) -> dict[str, object]:
    """Capture all persisted historical content rather than reinterpreting it."""
    tables = (
        "llm_catalogs",
        "llm_catalog_snapshots",
        "llm_catalog_entries",
        "model_metadata_source_snapshots",
        "agents",
        "workspace_model_settings",
        "events",
    )
    with engine.connect() as connection:
        return {
            table: connection.execute(
                sa.text(
                    "SELECT coalesce(jsonb_agg(to_jsonb(t) "
                    "ORDER BY to_jsonb(t)::text), '[]'::jsonb) "
                    f"FROM {table} t"
                )
            ).scalar_one()
            for table in tables
        }


def test_old_only_upgrade_is_sql_only_and_preserves_history(
    database: _Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First-fetch failure cannot be a prerequisite for a valid schema upgrade."""
    before = _preserved_rows(database.engine)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Migration must not fetch or decode application data")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(
        "azents.core.model_catalog_source.decode_catalog_source", forbidden
    )
    command.upgrade(database.config, _CUTOVER)
    assert _preserved_rows(database.engine) == before
    with database.engine.connect() as connection:
        authorities = {
            row.source_key: row.current_snapshot_id
            for row in connection.execute(
                sa.text(
                    "SELECT source_key, current_snapshot_id FROM model_metadata_sources"
                )
            ).all()
        }
        assert authorities == {"genai_prices": None, CATALOG_SOURCE_KEY: None}
        attempt = connection.execute(
            sa.text(
                "SELECT status, failure_code, failure_message, produced_snapshot_id "
                "FROM llm_catalog_sync_attempts WHERE id=:id"
            ),
            {"id": _OLD_ATTEMPT},
        ).one()
        assert attempt.status == "failed"
        assert attempt.failure_code and attempt.failure_message
        assert len(attempt.failure_message) < 1000
        assert attempt.produced_snapshot_id is None


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO model_metadata_sources(source_key) "
        "VALUES('genai_prices') ON CONFLICT DO NOTHING",
        "UPDATE model_metadata_sources SET current_snapshot_id=NULL "
        "WHERE source_key='genai_prices'",
        "DELETE FROM model_metadata_sources WHERE source_key='genai_prices'",
        "UPDATE model_metadata_source_snapshots SET model_count=2 "
        "WHERE source_key='genai_prices'",
        "DELETE FROM model_metadata_source_snapshots WHERE id='"
        + _OLD_UNUSED_SOURCE
        + "'",
    ],
    ids=[
        "authority-insert",
        "authority-update",
        "authority-delete",
        "snapshot-update",
        "unreferenced-snapshot-delete",
    ],
)
def test_retired_authority_is_frozen(cutover: _Database, statement: str) -> None:
    """No direct SQL writer may revive or purge the retained authority."""
    with _rejected(cutover.engine) as connection:
        connection.execute(sa.text(statement))


def test_retired_snapshot_insert_and_successful_attempt_are_rejected(
    cutover: _Database,
) -> None:
    """Old collectors cannot publish another snapshot or reuse old success."""
    with _rejected(cutover.engine) as connection:
        _source(
            connection,
            snapshot_id="r" * 32,
            source_key="genai_prices",
            source_kind="genai_prices",
            schema="1",
            payload="{}",
            content_hash="r" * 64,
        )
    with _rejected(cutover.engine) as connection:
        connection.execute(
            sa.text(
                "UPDATE llm_catalog_sync_attempts SET status='succeeded', "
                "produced_snapshot_id=:source WHERE id=:id"
            ),
            {"source": _OLD_SOURCE, "id": _OLD_ATTEMPT},
        )
    with cutover.engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE llm_catalog_sync_attempts SET status='failed', "
                "failure_message='Retired writer rejected.' WHERE id=:id"
            ),
            {"id": _OLD_ATTEMPT},
        )


@pytest.mark.parametrize(
    "bad_field", ["source_key", "source_kind", "source_schema_version"]
)
def test_new_source_snapshot_contract_is_enforced(
    cutover: _Database, bad_field: str
) -> None:
    """Source key, kind and schema are checked for both insert and update."""
    with cutover.engine.begin() as connection:
        _new_source(connection, snapshot_id=_NEW_SOURCE)
        if bad_field == "source_key":
            connection.execute(
                sa.text(
                    "INSERT INTO model_metadata_sources(source_key) VALUES('wrong')"
                )
            )
    with _rejected(cutover.engine) as connection:
        connection.execute(
            sa.text(
                "UPDATE model_metadata_source_snapshots "
                f"SET {bad_field}='wrong' WHERE id=:id"
            ),
            {"id": _NEW_SOURCE},
        )
    with _rejected(cutover.engine) as connection:
        _source(
            connection,
            snapshot_id="z" * 32,
            source_key="wrong" if bad_field == "source_key" else CATALOG_SOURCE_KEY,
            source_kind="wrong" if bad_field == "source_kind" else CATALOG_SOURCE_KIND,
            schema="wrong"
            if bad_field == "source_schema_version"
            else CATALOG_SOURCE_SCHEMA_VERSION,
            payload="{}",
            content_hash="z" * 64,
        )


@pytest.mark.parametrize("target", [_OLD_SOURCE, "missing" * 4 + "xxxx"])
def test_new_authority_pointer_requires_matching_source(
    cutover: _Database, target: str
) -> None:
    """Deferred existence does not permit a retired or absent source owner."""
    with _rejected(cutover.engine) as connection:
        connection.execute(
            sa.text(
                "UPDATE model_metadata_sources SET current_snapshot_id=:target "
                "WHERE source_key=:key"
            ),
            {"target": target, "key": CATALOG_SOURCE_KEY},
        )


@pytest.mark.parametrize("scope", ["system", "integration"])
@pytest.mark.parametrize(
    "case", ["old-schema", "genai-version", "old-source", "no-source", "valid"]
)
def test_conversation_candidate_contract(
    cutover: _Database, scope: str, case: str
) -> None:
    """System requires the new source; integration may use account facts alone."""
    with cutover.engine.begin() as connection:
        _new_source(connection, snapshot_id=_NEW_SOURCE)
        if scope == "integration":
            _catalog(
                connection,
                catalog_id="j" * 32,
                scope=scope,
                purpose="conversation",
                integration_id=_INTEGRATION,
                provider="openai",
            )
    admitted = case == "valid" or case == "no-source" and scope == "integration"
    source = (
        _OLD_SOURCE
        if case == "old-source"
        else None
        if case == "no-source"
        else _NEW_SOURCE
    )

    def insert(connection: Connection) -> None:
        _snapshot(
            connection,
            snapshot_id=_NEW_SNAPSHOT,
            catalog_id=_CATALOG if scope == "system" else "j" * 32,
            source_id=source,
            schema="1" if case == "old-schema" else "2",
            genai_version="old" if case == "genai-version" else None,
        )

    if admitted:
        with cutover.engine.begin() as connection:
            insert(connection)
    else:
        with _rejected(cutover.engine) as connection:
            insert(connection)


def test_image_catalog_is_exempt_from_conversation_source_contract(
    cutover: _Database,
) -> None:
    """Purpose-separated image registry rows do not need conversation provenance."""
    with cutover.engine.begin() as connection:
        _catalog(
            connection,
            catalog_id="m" * 32,
            scope="integration",
            purpose="image_generation",
            integration_id=_INTEGRATION,
            provider="openai",
        )
        _snapshot(
            connection,
            snapshot_id="f" * 32,
            catalog_id="m" * 32,
            source_id=None,
            schema=None,
            genai_version=None,
        )
        connection.execute(
            sa.text(
                "UPDATE llm_catalogs SET current_snapshot_id=:snapshot WHERE id=:id"
            ),
            {"snapshot": "f" * 32, "id": "m" * 32},
        )


@pytest.mark.parametrize(
    "case", ["reuse-old", "wrong-owner", "missing", "clear-success"]
)
def test_catalog_pointer_change_cannot_bypass_admission(
    cutover: _Database, case: str
) -> None:
    """An old candidate reused without INSERT still fails pointer publication."""
    with cutover.engine.begin() as connection:
        _new_source(connection, snapshot_id=_NEW_SOURCE)
        _snapshot(
            connection,
            snapshot_id=_NEW_SNAPSHOT,
            catalog_id=_CATALOG,
            source_id=_NEW_SOURCE,
            schema="2",
            genai_version=None,
        )
        if case == "wrong-owner":
            _catalog(
                connection,
                catalog_id="d" * 32,
                scope="system",
                purpose="conversation",
                integration_id=None,
                provider="anthropic",
            )
        connection.execute(
            sa.text("UPDATE llm_catalogs SET current_snapshot_id=:target WHERE id=:id"),
            {"target": _NEW_SNAPSHOT, "id": _CATALOG},
        )
    target = (
        _OLD_SNAPSHOT
        if case == "reuse-old"
        else _NEW_SNAPSHOT
        if case == "wrong-owner"
        else "x" * 32
        if case == "missing"
        else None
    )
    with _rejected(cutover.engine) as connection:
        connection.execute(
            sa.text("UPDATE llm_catalogs SET current_snapshot_id=:target WHERE id=:id"),
            {"target": target, "id": "d" * 32 if case == "wrong-owner" else _CATALOG},
        )


def test_unchanged_old_pointer_allows_operational_updates(cutover: _Database) -> None:
    """Old historical pointers do not block lease and diagnostic operations."""
    with cutover.engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE llm_catalogs SET current_snapshot_id=current_snapshot_id, "
                "latest_attempt_id=:attempt WHERE id=:id"
            ),
            {"attempt": _OLD_ATTEMPT, "id": _CATALOG},
        )
    with cutover.engine.connect() as connection:
        assert (
            connection.execute(
                sa.text("SELECT current_snapshot_id FROM llm_catalogs WHERE id=:id"),
                {"id": _CATALOG},
            ).scalar_one()
            == _OLD_SNAPSHOT
        )


@pytest.mark.parametrize(
    "kind", ["source-snapshot", "catalog-snapshot", "source-authority"]
)
def test_referenced_source_and_snapshot_deletion_is_rejected(
    cutover: _Database, kind: str
) -> None:
    """Deletion cannot orphan current pointers or strip projection provenance."""
    with cutover.engine.begin() as connection:
        _new_source(connection, snapshot_id=_NEW_SOURCE)
        _snapshot(
            connection,
            snapshot_id=_NEW_SNAPSHOT,
            catalog_id=_CATALOG,
            source_id=_NEW_SOURCE,
            schema="2",
            genai_version=None,
        )
        connection.execute(
            sa.text("UPDATE llm_catalogs SET current_snapshot_id=:target WHERE id=:id"),
            {"target": _NEW_SNAPSHOT, "id": _CATALOG},
        )
    table, column, value = {
        "source-snapshot": ("model_metadata_source_snapshots", "id", _NEW_SOURCE),
        "catalog-snapshot": ("llm_catalog_snapshots", "id", _NEW_SNAPSHOT),
        "source-authority": (
            "model_metadata_sources",
            "source_key",
            CATALOG_SOURCE_KEY,
        ),
    }[kind]
    with _rejected(cutover.engine) as connection:
        connection.execute(
            sa.text(f"DELETE FROM {table} WHERE {column}=:value"), {"value": value}
        )


def test_pointer_replace_then_superseded_snapshot_delete_is_valid(
    cutover: _Database,
) -> None:
    """Deferred NO ACTION checks preserve existing replace-and-cleanup transactions."""
    with cutover.engine.begin() as connection:
        _new_source(connection, snapshot_id=_NEW_SOURCE)
        _snapshot(
            connection,
            snapshot_id=_NEW_SNAPSHOT,
            catalog_id=_CATALOG,
            source_id=_NEW_SOURCE,
            schema="2",
            genai_version=None,
        )
        connection.execute(
            sa.text("UPDATE llm_catalogs SET current_snapshot_id=:target WHERE id=:id"),
            {"target": _NEW_SNAPSHOT, "id": _CATALOG},
        )
        connection.execute(
            sa.text("DELETE FROM llm_catalog_snapshots WHERE id=:id"),
            {"id": _OLD_SNAPSHOT},
        )
    with cutover.engine.connect() as connection:
        assert (
            connection.execute(
                sa.text("SELECT count(*) FROM llm_catalog_snapshots WHERE id=:id"),
                {"id": _OLD_SNAPSHOT},
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize("parent", ["catalog", "integration"])
def test_parent_deletion_cascade_remains_valid(cutover: _Database, parent: str) -> None:
    """Owner removal deletes the current pointer and its snapshots together."""
    with cutover.engine.begin() as connection:
        if parent == "catalog":
            connection.execute(
                sa.text("DELETE FROM llm_catalogs WHERE id=:id"), {"id": _CATALOG}
            )
        else:
            _catalog(
                connection,
                catalog_id="j" * 32,
                scope="integration",
                purpose="conversation",
                integration_id=_INTEGRATION,
                provider="openai",
            )
            _snapshot(
                connection,
                snapshot_id=_NEW_SNAPSHOT,
                catalog_id="j" * 32,
                source_id=None,
                schema="2",
                genai_version=None,
            )
            connection.execute(
                sa.text(
                    "UPDATE llm_catalogs SET current_snapshot_id=:target WHERE id=:id"
                ),
                {"target": _NEW_SNAPSHOT, "id": "j" * 32},
            )
            connection.execute(
                sa.text("DELETE FROM llm_provider_integrations WHERE id=:id"),
                {"id": _INTEGRATION},
            )
    with cutover.engine.connect() as connection:
        assert (
            connection.execute(
                sa.text("SELECT count(*) FROM llm_catalogs WHERE id=:id"),
                {"id": _CATALOG if parent == "catalog" else "j" * 32},
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize(
    "case", ["source-orphan", "source-owner", "catalog-orphan", "catalog-owner"]
)
def test_inconsistent_pointer_preflight_rejects_atomically(
    database: _Database, case: str
) -> None:
    """Inconsistent old data remains untouched for explicit operator correction."""
    with database.engine.begin() as connection:
        if case.startswith("source"):
            if case == "source-owner":
                connection.execute(
                    sa.text(
                        "INSERT INTO model_metadata_sources"
                        "(source_key,current_snapshot_id) "
                        "VALUES('other_history',:target)"
                    ),
                    {"target": _OLD_SOURCE},
                )
            else:
                connection.execute(
                    sa.text(
                        "UPDATE model_metadata_sources "
                        "SET current_snapshot_id=:target "
                        "WHERE source_key='genai_prices'"
                    ),
                    {"target": "x" * 32},
                )
        elif case == "catalog-owner":
            _catalog(
                connection,
                catalog_id="d" * 32,
                scope="system",
                purpose="conversation",
                integration_id=None,
                provider="anthropic",
            )
            connection.execute(
                sa.text(
                    "UPDATE llm_catalogs SET current_snapshot_id=:target WHERE id=:id"
                ),
                {"target": _OLD_SNAPSHOT, "id": "d" * 32},
            )
        else:
            connection.execute(
                sa.text(
                    "UPDATE llm_catalogs SET current_snapshot_id=:target WHERE id=:id"
                ),
                {"target": "x" * 32, "id": _CATALOG},
            )
    before = _preserved_rows(database.engine)
    with pytest.raises(DBAPIError):
        command.upgrade(database.config, _CUTOVER)
    assert _preserved_rows(database.engine) == before
    with database.engine.connect() as connection:
        assert (
            connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == _PARENT
        )
        assert (
            connection.execute(
                sa.text(
                    "SELECT count(*) FROM model_metadata_sources WHERE source_key=:key"
                ),
                {"key": CATALOG_SOURCE_KEY},
            ).scalar_one()
            == 0
        )


def test_irreversible_downgrade_keeps_writer_guards(cutover: _Database) -> None:
    """Rejected binary rollback does not partially remove the migrated contract."""
    with pytest.raises(RuntimeError, match="irreversible|restore|rollback|reversal"):
        command.downgrade(cutover.config, _PARENT)
    with cutover.engine.connect() as connection:
        assert (
            connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == _CUTOVER
        )
    with _rejected(cutover.engine) as connection:
        connection.execute(
            sa.text(
                "DELETE FROM model_metadata_sources WHERE source_key='genai_prices'"
            )
        )


def test_current_pointer_foreign_keys_are_deferred_no_action(
    cutover: _Database,
) -> None:
    """Current pointers cannot be orphaned or silently cleared by FK deletion."""
    with cutover.engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                "SELECT c.conrelid::regclass::text AS table_name, "
                "c.condeferrable, c.condeferred, c.confdeltype "
                "FROM pg_constraint c JOIN pg_attribute a "
                "ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey) "
                "WHERE c.contype='f' AND a.attname='current_snapshot_id' "
                "AND c.conrelid IN "
                "('model_metadata_sources'::regclass,'llm_catalogs'::regclass)"
            )
        ).all()
        assert {row.table_name for row in rows} == {
            "model_metadata_sources",
            "llm_catalogs",
        }
        assert all(
            row.condeferrable and row.condeferred and row.confdeltype == "a"
            for row in rows
        )


def test_new_source_pointer_replace_then_snapshot_delete_is_valid(
    cutover: _Database,
) -> None:
    """A superseded new-source snapshot is not subject to retired-history freeze."""
    with cutover.engine.begin() as connection:
        _new_source(connection, snapshot_id=_NEW_SOURCE)
    with cutover.engine.begin() as connection:
        _new_source(connection, snapshot_id="q" * 32)
        connection.execute(
            sa.text("DELETE FROM model_metadata_source_snapshots WHERE id=:id"),
            {"id": _NEW_SOURCE},
        )
    with cutover.engine.connect() as connection:
        assert (
            connection.execute(
                sa.text(
                    "SELECT current_snapshot_id FROM model_metadata_sources "
                    "WHERE source_key=:key"
                ),
                {"key": CATALOG_SOURCE_KEY},
            ).scalar_one()
            == "q" * 32
        )


def test_preflight_does_not_clear_an_already_active_replacement_source(
    database: _Database,
) -> None:
    """An unexpected pre-existing replacement authority needs operator review."""
    with database.engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO model_metadata_sources(source_key) VALUES(:key)"),
            {"key": CATALOG_SOURCE_KEY},
        )
        _new_source(connection, snapshot_id=_NEW_SOURCE)
    before = _preserved_rows(database.engine)
    with pytest.raises(DBAPIError):
        command.upgrade(database.config, _CUTOVER)
    assert _preserved_rows(database.engine) == before
    with database.engine.connect() as connection:
        pointers = {
            row.source_key: row.current_snapshot_id
            for row in connection.execute(
                sa.text(
                    "SELECT source_key,current_snapshot_id FROM model_metadata_sources"
                )
            )
        }
        assert pointers == {
            "genai_prices": _OLD_SOURCE,
            CATALOG_SOURCE_KEY: _NEW_SOURCE,
        }
        assert (
            connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == _PARENT
        )


def test_historical_success_metadata_is_retained_but_cannot_be_republished(
    database: _Database,
) -> None:
    """An inert prior success is not relabeled or turned into a new publication."""
    historical_attempt = "b" * 32
    with database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO llm_catalog_sync_attempts "
                "(id, source_key, status, started_at, finished_at, "
                "produced_snapshot_id, fetched_count, matched_count, "
                "skipped_count, hidden_count) VALUES "
                "(:id, 'genai_prices', 'succeeded', now(), now(), :source, "
                "1, 1, 0, 0)"
            ),
            {"id": historical_attempt, "source": _OLD_SOURCE},
        )
        before = connection.execute(
            sa.text("SELECT to_jsonb(t) FROM llm_catalog_sync_attempts t WHERE id=:id"),
            {"id": historical_attempt},
        ).scalar_one()
    command.upgrade(database.config, _CUTOVER)
    with database.engine.begin() as connection:
        after = connection.execute(
            sa.text("SELECT to_jsonb(t) FROM llm_catalog_sync_attempts t WHERE id=:id"),
            {"id": historical_attempt},
        ).scalar_one()
        assert after == before
        connection.execute(
            sa.text(
                "UPDATE llm_catalog_sync_attempts "
                "SET diagnostics=CAST(:diagnostics AS jsonb) WHERE id=:id"
            ),
            {
                "id": historical_attempt,
                "diagnostics": json.dumps({"historical_read": True}),
            },
        )
    with _rejected(database.engine) as connection:
        connection.execute(
            sa.text(
                "UPDATE llm_catalog_sync_attempts SET produced_snapshot_id=:source "
                "WHERE id=:id"
            ),
            {"id": historical_attempt, "source": _OLD_UNUSED_SOURCE},
        )
    with _rejected(database.engine) as connection:
        connection.execute(
            sa.text(
                "INSERT INTO llm_catalog_sync_attempts "
                "(id, source_key, status, started_at, produced_snapshot_id, "
                "fetched_count, matched_count, skipped_count, hidden_count) VALUES "
                "(:id, 'genai_prices', 'succeeded', now(), :source, 1, 1, 0, 0)"
            ),
            {"id": "k" * 32, "source": _OLD_SOURCE},
        )


@pytest.mark.parametrize(
    "case",
    [
        "catalog-provider",
        "catalog-purpose",
        "catalog-scope",
        "catalog-integration",
        "catalog-id",
        "snapshot-owner",
        "snapshot-id",
    ],
)
def test_published_catalog_and_snapshot_identity_cannot_be_changed(
    cutover: _Database, case: str
) -> None:
    """A validated target cannot be converted into a different owner or purpose."""
    with cutover.engine.begin() as connection:
        _new_source(connection, snapshot_id=_NEW_SOURCE)
        _snapshot(
            connection,
            snapshot_id=_NEW_SNAPSHOT,
            catalog_id=_CATALOG,
            source_id=_NEW_SOURCE,
            schema="2",
            genai_version=None,
        )
        _catalog(
            connection,
            catalog_id="d" * 32,
            scope="system",
            purpose="conversation",
            integration_id=None,
            provider="anthropic",
        )
        connection.execute(
            sa.text("UPDATE llm_catalogs SET current_snapshot_id=:target WHERE id=:id"),
            {"target": _NEW_SNAPSHOT, "id": _CATALOG},
        )
    assignment = {
        "catalog-provider": "provider='google_gemini'",
        "catalog-purpose": "purpose='image_generation'",
        "catalog-scope": "scope='integration', provider_integration_id=:integration",
        "catalog-integration": "provider_integration_id=:integration",
        "catalog-id": "id=:replacement",
        "snapshot-owner": "catalog_id=:owner",
        "snapshot-id": "id=:replacement",
    }[case]
    table = "llm_catalog_snapshots" if case.startswith("snapshot") else "llm_catalogs"
    row_id = _NEW_SNAPSHOT if case.startswith("snapshot") else _CATALOG
    with pytest.raises(DBAPIError) as failure, cutover.engine.begin() as connection:
        connection.execute(
            sa.text(f"UPDATE {table} SET {assignment} WHERE id=:id"),
            {
                "id": row_id,
                "integration": _INTEGRATION,
                "owner": "d" * 32,
                "replacement": "x" * 32,
            },
        )
    assert isinstance(failure.value.orig, psycopg.Error)
    assert failure.value.orig.sqlstate == "23514"
