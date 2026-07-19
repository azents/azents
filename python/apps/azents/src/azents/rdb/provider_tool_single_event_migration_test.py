"""Single provider-tool event migration tests."""

import datetime
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
    AttachmentOutputPart,
    ClientToolResultPayload,
    FileOutputPart,
    ProviderToolCallPayload,
)

_MIGRATION_PATH = (
    PROJECT_ROOT / "db-schemas/rdb/migrations/versions/"
    "e95f7e9143c5_use_single_provider_tool_events.py"
)
_EVENT_KIND_VALUES = (
    "user_message",
    "goal_continuation",
    "goal_updated",
    "action_message",
    "agent_message",
    "action_execution_result",
    "skill_loaded",
    "goal_briefing",
    "assistant_message",
    "reasoning",
    "client_tool_call",
    "client_tool_result",
    "provider_tool_call",
    "provider_tool_result",
    "turn_marker",
    "run_marker",
    "interrupted",
    "compaction_marker",
    "compaction_summary",
    "system_reminder",
    "system_error",
    "unknown_adapter_output",
)


def _load_migration() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "provider_tool_single_event_migration",
        _MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Single provider-tool migration could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _artifact(item_type: str, item_id: str) -> dict[str, object]:
    return {
        "compat_key": "litellm:responses:openai:gpt-5.1:1",
        "adapter": "litellm",
        "native_format": "responses",
        "provider": "openai",
        "model": "gpt-5.1",
        "schema_version": "1",
        "item": {"type": item_type, "id": item_id},
    }


def _attachment(source: str) -> dict[str, object]:
    return {
        "attachment_id": f"attachment-{source}",
        "uri": f"exchange://{source}",
        "name": f"{source}.png",
        "media_type": "image/png",
        "size": 68,
        "created_at": "2026-07-19T00:00:00Z",
        "source": source,
        "availability": "available",
    }


def _rows(connection: sa.Connection) -> dict[str, tuple[str, dict[str, object]]]:
    rows = connection.execute(
        sa.text("SELECT id, kind::text AS kind, payload FROM events ORDER BY id")
    ).mappings()
    result: dict[str, tuple[str, dict[str, object]]] = {}
    for row in rows:
        event_id = row["id"]
        kind = row["kind"]
        payload = row["payload"]
        if not isinstance(event_id, str) or not isinstance(kind, str):
            raise RuntimeError("Migration test returned invalid event identity.")
        if not isinstance(payload, dict):
            raise RuntimeError("Migration test returned invalid payload.")
        result[event_id] = (kind, {str(key): value for key, value in payload.items()})
    return result


def test_single_provider_tool_event_upgrade_and_downgrade(
    check_docker_availability: None,
) -> None:
    """Migrate kinds, canonical output parts, and the PostgreSQL enum."""
    del check_docker_availability
    migration = _load_migration()
    postgres_image = get_docker_hub_image("postgres:17")
    with PostgresContainer(postgres_image, driver="psycopg") as postgres:
        engine = sa.create_engine(postgres.get_connection_url())
        try:
            with engine.begin() as connection:
                values = ", ".join(f"'{value}'" for value in _EVENT_KIND_VALUES)
                connection.execute(
                    sa.text(f"CREATE TYPE event_kind AS ENUM ({values})")
                )
                connection.execute(
                    sa.text(
                        """
                        CREATE TABLE events (
                            id TEXT PRIMARY KEY,
                            kind event_kind NOT NULL,
                            payload JSONB NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL
                        )
                        """
                    )
                )
                file_part = {
                    "type": "file",
                    "model_file_id": "model-file-1",
                    "media_type": "image/png",
                    "name": "generated.png",
                    "size": 68,
                    "kind": "image",
                    "metadata": {},
                }
                provider_result = {
                    "call_id": "image-1",
                    "name": "image_generation",
                    "status": "completed",
                    "semantic": {
                        "input": None,
                        "output": [file_part],
                        "references": [],
                    },
                    "attachments": [_attachment("provider_tool")],
                    "native_artifact": _artifact("image_generation_call", "image-1"),
                }
                provider_call = {
                    "call_id": "search-1",
                    "name": "web_search",
                    "status": "completed",
                    "semantic": {
                        "input": '{"query":"Azents"}',
                        "output": "found",
                        "references": [],
                    },
                    "attachments": [_attachment("provider_tool")],
                    "native_artifact": _artifact("web_search_call", "search-1"),
                }
                client_result = {
                    "call_id": "client-1",
                    "name": "image_generation",
                    "status": "completed",
                    "output": [file_part],
                    "attachments": [_attachment("client_tool")],
                    "metadata": {},
                }
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO events (id, kind, payload, created_at)
                        VALUES
                            ('provider-result', 'provider_tool_result',
                                CAST(:provider_result AS JSONB), :created_at),
                            ('provider-call', 'provider_tool_call',
                                CAST(:provider_call AS JSONB), :created_at),
                            ('client-result', 'client_tool_result',
                                CAST(:client_result AS JSONB), :created_at)
                        """
                    ),
                    {
                        "provider_result": json.dumps(provider_result),
                        "provider_call": json.dumps(provider_call),
                        "client_result": json.dumps(client_result),
                        "created_at": datetime.datetime(
                            2026,
                            7,
                            19,
                            tzinfo=datetime.UTC,
                        ),
                    },
                )
                operations = Operations(MigrationContext.configure(connection))
                with patch.object(migration, "op", operations):
                    migration.upgrade()

                upgraded = _rows(connection)
                result_kind, result_payload = upgraded["provider-result"]
                assert result_kind == "provider_tool_call"
                result = ProviderToolCallPayload.model_validate(result_payload)
                assert isinstance(result.semantic.output, list)
                assert isinstance(result.semantic.output[0], FileOutputPart)
                assert isinstance(result.semantic.output[1], AttachmentOutputPart)
                assert "attachments" not in result_payload

                _, call_payload = upgraded["provider-call"]
                call = ProviderToolCallPayload.model_validate(call_payload)
                assert isinstance(call.semantic.output, list)
                assert call.semantic.output[0].type == "text"
                assert isinstance(call.semantic.output[1], AttachmentOutputPart)

                _, client_payload = upgraded["client-result"]
                client = ClientToolResultPayload.model_validate(client_payload)
                assert isinstance(client.output, list)
                assert isinstance(client.output[1], AttachmentOutputPart)
                assert "attachments" not in client_payload

                enum_values = connection.execute(
                    sa.text(
                        """
                        SELECT enumlabel FROM pg_enum
                        JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
                        WHERE pg_type.typname = 'event_kind'
                        ORDER BY enumsortorder
                        """
                    )
                ).scalars()
                assert "provider_tool_result" not in list(enum_values)

                post_upgrade_generic_call = {
                    "call_id": "search-interrupted",
                    "name": "web_search",
                    "status": "interrupted",
                    "semantic": {
                        "input": '{"query":"rollback"}',
                        "output": [],
                        "references": [],
                    },
                    "native_artifact": _artifact(
                        "web_search_call",
                        "search-interrupted",
                    ),
                }
                post_upgrade_image_call = {
                    "call_id": "image-running",
                    "name": "image_generation",
                    "status": "running",
                    "semantic": {
                        "input": None,
                        "output": [],
                        "references": [],
                    },
                    "native_artifact": _artifact(
                        "image_generation_call",
                        "image-running",
                    ),
                }
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO events (id, kind, payload, created_at)
                        VALUES
                            ('post-upgrade-generic', 'provider_tool_call',
                                CAST(:generic AS JSONB), :created_at),
                            ('post-upgrade-image', 'provider_tool_call',
                                CAST(:image AS JSONB), :created_at)
                        """
                    ),
                    {
                        "generic": json.dumps(post_upgrade_generic_call),
                        "image": json.dumps(post_upgrade_image_call),
                        "created_at": datetime.datetime(
                            2026,
                            7,
                            19,
                            tzinfo=datetime.UTC,
                        ),
                    },
                )

                with patch.object(migration, "op", operations):
                    migration.downgrade()

                downgraded = _rows(connection)
                assert downgraded["provider-result"][0] == "provider_tool_result"
                assert downgraded["post-upgrade-generic"][0] == "provider_tool_call"
                assert downgraded["post-upgrade-generic"][1]["status"] == "failed"
                assert downgraded["post-upgrade-image"][0] == "provider_tool_result"
                assert downgraded["post-upgrade-image"][1]["status"] == "interrupted"
                restored_provider = downgraded["provider-result"][1]
                restored_provider_attachments = restored_provider["attachments"]
                assert isinstance(restored_provider_attachments, list)
                assert len(restored_provider_attachments) == 1
                restored_semantic = restored_provider["semantic"]
                assert isinstance(restored_semantic, dict)
                assert restored_semantic["output"] == [file_part]
                restored_client = downgraded["client-result"][1]
                restored_client_attachments = restored_client["attachments"]
                assert isinstance(restored_client_attachments, list)
                assert len(restored_client_attachments) == 1
                assert restored_client["output"] == [file_part]
        finally:
            engine.dispose()
