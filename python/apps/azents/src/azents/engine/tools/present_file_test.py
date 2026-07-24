"""present_file tool tests."""

import datetime
import json
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Success

from azents.core.enums import (
    ExchangeFileOrigin,
    ExchangeFileProvenanceKind,
    ExchangeFileStatus,
)
from azents.engine.run.types import FunctionToolResult
from azents.engine.tools.present_file import make_present_file_tool
from azents.engine.tools.testing import FakeSharedStorage
from azents.repos.exchange_file.data import ExchangeFile
from azents.services.session_resource_authority import SessionResourceAuthority

_NOW = datetime.datetime.now(datetime.timezone.utc)


def _make_artifact_file() -> ExchangeFile:
    """Create artifact ExchangeFile for tests."""
    return ExchangeFile(
        id="b" * 32,
        workspace_id="workspace-1",
        agent_id="agent-1",
        origin_type=ExchangeFileOrigin.ARTIFACT,
        status=ExchangeFileStatus.AVAILABLE,
        object_key="exchange/workspace-1/artifacts/b/original",
        filename="result.txt",
        media_type="text/plain",
        size_bytes=12,
        sha256="1" * 64,
        provenance_kind=ExchangeFileProvenanceKind.HUMAN,
        source_user_id="user-1",
        source_agent_id=None,
        source_run_id=None,
        source_tool_name=None,
        source_provider=None,
        source_exchange_file_id=None,
        retention_root_session_id="session-1",
        retention_bound_at=_NOW,
        preview_thumbnail_file_id=None,
        preview_thumbnail_uri=None,
        preview_title="result.txt",
        preview_summary="stored preview",
        preview_thumbnail_media_type=None,
        preview_thumbnail_width=None,
        preview_thumbnail_height=None,
        preview_generated_at=None,
        expires_at=_NOW + datetime.timedelta(days=30),
        expired_at=None,
        blob_deleted_at=None,
        created_at=_NOW,
    )


@pytest.mark.asyncio
async def test_present_file_exports_runtime_file_as_exchange_artifact() -> None:
    """Return runtime file as artifact URI attachment."""
    storage = FakeSharedStorage(files={"/workspace/agent/result.txt": b"hello world!"})
    artifact = _make_artifact_file()
    service = AsyncMock()
    service.create_for_authority.return_value = Success(artifact)
    tool = make_present_file_tool(
        session_storage=storage,
        exchange_file_service=service,
        authority=_authority(),
    )

    result = await tool.handler(json.dumps({"paths": ["/workspace/agent/result.txt"]}))

    assert isinstance(result, FunctionToolResult)
    assert isinstance(result.output, list)
    attachment = result.output[1]
    assert attachment["type"] == "attachment"
    assert attachment["uri"] == artifact.uri
    assert attachment["preview_summary"] == "stored preview"
    service.create_for_authority.assert_awaited_once_with(
        authority=_authority(),
        provenance_kind=ExchangeFileProvenanceKind.TOOL,
        source_tool_name="present_file",
        source_provider=None,
        filename="result.txt",
        media_type="text/plain",
        body=b"hello world!",
    )


@pytest.mark.asyncio
async def test_present_file_reports_missing_path() -> None:
    """Include nonexistent runtime path in errors."""
    storage = FakeSharedStorage()
    service = AsyncMock()
    tool = make_present_file_tool(
        session_storage=storage,
        exchange_file_service=service,
        authority=_authority(),
    )

    result = await tool.handler(json.dumps({"paths": ["/workspace/agent/missing.txt"]}))

    assert isinstance(result, FunctionToolResult)
    assert isinstance(result.output, list)
    text = result.output[0]
    assert isinstance(text["text"], str)
    assert "File not found or inaccessible" in text["text"]
    service.create_for_authority.assert_not_awaited()


@pytest.mark.asyncio
async def test_present_file_rejects_tmp_path() -> None:
    """Do not export temporary file as user-facing artifact."""
    storage = FakeSharedStorage(files={"/tmp/output.txt": b"temporary"})
    service = AsyncMock()
    tool = make_present_file_tool(
        session_storage=storage,
        exchange_file_service=service,
        authority=_authority(),
    )

    result = await tool.handler(json.dumps({"paths": ["/tmp/output.txt"]}))

    assert isinstance(result, FunctionToolResult)
    assert isinstance(result.output, list)
    text = result.output[0]
    assert isinstance(text["text"], str)
    assert "Only files under /workspace/agent can be presented" in text["text"]
    service.create_for_authority.assert_not_awaited()


@pytest.mark.asyncio
async def test_present_file_rejects_root_escape() -> None:
    """Do not export lexical root escape path."""
    storage = FakeSharedStorage(files={"/workspace/agent/../../etc/passwd": b"x"})
    service = AsyncMock()
    tool = make_present_file_tool(
        session_storage=storage,
        exchange_file_service=service,
        authority=_authority(),
    )

    result = await tool.handler(
        json.dumps({"paths": ["/workspace/agent/../../etc/passwd"]})
    )

    assert isinstance(result, FunctionToolResult)
    assert isinstance(result.output, list)
    text = result.output[0]
    assert isinstance(text["text"], str)
    assert "Only files under /workspace/agent can be presented" in text["text"]
    service.create_for_authority.assert_not_awaited()


def _authority() -> SessionResourceAuthority:
    """Create canonical Session/Run authority for tests."""
    return SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="session-1",
        run_id="run-1",
        run_index=1,
        owner_generation=1,
    )
