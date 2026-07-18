"""Provider-tool semantic payload migration tests."""

import importlib.util
import json
import types
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from azcommon.testing.images import get_docker_hub_image
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT
from azents.engine.events.types import (
    ProviderToolCallPayload,
    ProviderToolResultPayload,
)

_MIGRATION_PATH = (
    PROJECT_ROOT / "db-schemas/rdb/migrations/versions/"
    "25bc37eadace_normalize_provider_tool_semantic_content.py"
)


def _load_migration() -> types.ModuleType:
    """Load the generated migration module from its revision file."""
    spec = importlib.util.spec_from_file_location(
        "provider_tool_semantic_migration",
        _MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Provider-tool semantic migration could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _native_artifact() -> dict[str, object]:
    """Return a valid persisted native artifact fixture."""
    return {
        "compat_key": "litellm:responses:openai:gpt-5.1:1",
        "adapter": "litellm",
        "native_format": "responses",
        "provider": "openai",
        "model": "gpt-5.1",
        "schema_version": "1",
        "item": {"type": "web_search_call", "id": "provider-1"},
    }


def _event_payloads(connection: sa.Connection) -> dict[str, dict[str, object]]:
    """Read and validate migration-test event payload rows."""
    payloads: dict[str, dict[str, object]] = {}
    rows = connection.execute(
        sa.text("SELECT id, payload FROM events ORDER BY id")
    ).mappings()
    for row in rows:
        event_id = row["id"]
        payload = row["payload"]
        if not isinstance(event_id, str) or not isinstance(payload, dict):
            raise RuntimeError("Migration test returned an invalid event row.")
        payloads[event_id] = {str(key): value for key, value in payload.items()}
    return payloads


def test_provider_tool_semantic_payload_upgrade_and_downgrade(
    check_docker_availability: None,
) -> None:
    """Rewrite legacy JSONB payloads and restore their previous contract."""
    del check_docker_availability
    migration = _load_migration()
    postgres_image = get_docker_hub_image("postgres:17")
    with PostgresContainer(postgres_image, driver="psycopg") as postgres:
        engine = sa.create_engine(postgres.get_connection_url())
        try:
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        CREATE TABLE events (
                            id TEXT PRIMARY KEY,
                            kind TEXT NOT NULL,
                            payload JSONB NOT NULL
                        )
                        """
                    )
                )
                legacy_call = {
                    "call_id": "provider-1",
                    "name": "web_search",
                    "arguments": '{"query":"Azents"}',
                    "native_artifact": _native_artifact(),
                }
                legacy_result = {
                    "call_id": "provider-2",
                    "status": "completed",
                    "output": "result text",
                    "attachments": [],
                    "native_artifact": _native_artifact(),
                }
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO events (id, kind, payload)
                        VALUES
                            ('call', 'provider_tool_call', CAST(:call AS JSONB)),
                            ('result', 'provider_tool_result', CAST(:result AS JSONB))
                        """
                    ),
                    {
                        "call": json.dumps(legacy_call),
                        "result": json.dumps(legacy_result),
                    },
                )
                operations = Operations(MigrationContext.configure(connection))
                with patch.object(migration, "op", operations):
                    migration.upgrade()

                upgraded = _event_payloads(connection)
                call_payload = ProviderToolCallPayload.model_validate(upgraded["call"])
                result_payload = ProviderToolResultPayload.model_validate(
                    upgraded["result"]
                )
                assert call_payload.status is None
                assert call_payload.semantic.input == '{"query":"Azents"}'
                assert call_payload.semantic.output == []
                assert call_payload.semantic.references == []
                assert call_payload.attachments == []
                assert result_payload.name is None
                assert result_payload.semantic.input is None
                assert result_payload.semantic.output == "result text"
                assert result_payload.semantic.references == []
                assert result_payload.attachments == []
                assert "arguments" not in upgraded["call"]
                assert "output" not in upgraded["result"]

                with patch.object(migration, "op", operations):
                    migration.downgrade()
                downgraded = _event_payloads(connection)
                assert downgraded["call"] == {
                    **legacy_call,
                    "status": None,
                }
                assert downgraded["result"] == {
                    **legacy_result,
                    "name": None,
                }
        finally:
            engine.dispose()
