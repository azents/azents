"""import_file tool tests."""

import datetime
import json
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success

from azents.core.enums import ArtifactStatus, ExchangeFileOrigin, ExchangeFileStatus
from azents.core.vfs import make_vfs_projection, make_vfs_source_revision
from azents.engine.run.types import FunctionToolError
from azents.engine.tools.import_file import make_import_file_tool
from azents.engine.tools.testing import FakeSharedStorage
from azents.repos.artifact.data import Artifact
from azents.repos.exchange_file.data import ExchangeFile
from azents.services.artifact import ArtifactDownload, ArtifactExpired
from azents.services.exchange_file import ExchangeFileDownload, FileNotFound
from azents.services.vfs import VfsResolvedFile

_NOW = datetime.datetime.now(datetime.timezone.utc)


def _make_artifact() -> Artifact:
    """Create Artifact for tests."""
    return Artifact(
        id="b" * 32,
        workspace_id="workspace-1",
        session_id="session-1",
        agent_id="agent-1",
        created_run_id="run-1",
        created_run_index=10,
        expires_at=_NOW + datetime.timedelta(days=7),
        name="artifact.txt",
        media_type="text/plain",
        size_bytes=11,
        storage_key="artifacts/workspace-1/session-1/10/b",
        status=ArtifactStatus.AVAILABLE,
        sha256="1" * 64,
        created_at=_NOW,
    )


def _make_artifact_service() -> AsyncMock:
    """Create ArtifactService mock for tests."""
    return AsyncMock()


class _VfsService:
    """VfsProjectionService test double for one managed resource."""

    def __init__(self) -> None:
        revision = make_vfs_source_revision(
            source_id="release:azents",
            source_kind="global_release",
            namespace="azents",
            entries=[
                (
                    "azents://skills/test/sample/references/checklist.md",
                    b"# Evidence checklist",
                    "text/markdown",
                )
            ],
        )
        self.projection = make_vfs_projection([revision])

    async def resolve_file(self, **kwargs: object) -> VfsResolvedFile:
        """Return the fixture entry from the run projection."""
        entry = self.projection.find(str(kwargs["uri"]))
        if entry is None:
            raise AssertionError("Missing VFS fixture entry")
        return VfsResolvedFile(
            projection_revision_id=self.projection.revision_id,
            projection_hash=self.projection.projection_hash,
            entry=entry,
        )


def _make_exchange_file() -> ExchangeFile:
    """Create ExchangeFile for tests."""
    return ExchangeFile(
        id="a" * 32,
        workspace_id="workspace-1",
        agent_id="agent-1",
        origin_type=ExchangeFileOrigin.UPLOAD,
        status=ExchangeFileStatus.AVAILABLE,
        object_key="exchange/workspace-1/uploads/a/original",
        filename="report.csv",
        media_type="text/csv",
        size_bytes=7,
        sha256="0" * 64,
        created_by_user_id="user-1",
        retention_root_session_id=None,
        retention_bound_at=None,
        preview_thumbnail_file_id=None,
        preview_thumbnail_uri=None,
        preview_title="report.csv",
        preview_summary=None,
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
async def test_import_file_writes_exchange_body_to_runtime() -> None:
    """Store Exchange file bytes to runtime destination."""
    storage = FakeSharedStorage()
    exchange_file = _make_exchange_file()
    service = AsyncMock()
    service.resolve_attachment.return_value = Success(
        ExchangeFileDownload(file=exchange_file, body=b"a,b\n1,2")
    )
    tool = make_import_file_tool(
        session_storage=storage,
        exchange_file_service=service,
        artifact_service=_make_artifact_service(),
        vfs_projection_service=None,
        session_id="session-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        run_id="run-1",
        user_id="user-1",
    )

    result = await tool.handler(
        json.dumps(
            {
                "uri": exchange_file.uri,
                "path": "/workspace/agent/report.csv",
            }
        )
    )

    assert isinstance(result, str)
    assert "/workspace/agent/report.csv" in result
    assert storage.put_calls == [("/workspace/agent/report.csv", b"a,b\n1,2")]


@pytest.mark.asyncio
async def test_import_file_defaults_to_tmp_uploads_path() -> None:
    """Store under transient uploads path when destination is omitted."""
    storage = FakeSharedStorage()
    exchange_file = _make_exchange_file()
    service = AsyncMock()
    service.resolve_attachment.return_value = Success(
        ExchangeFileDownload(file=exchange_file, body=b"a,b\n1,2")
    )
    tool = make_import_file_tool(
        session_storage=storage,
        exchange_file_service=service,
        artifact_service=_make_artifact_service(),
        vfs_projection_service=None,
        session_id="session-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        run_id="run-1",
        user_id="user-1",
    )

    result = await tool.handler(json.dumps({"uri": exchange_file.uri}))

    assert isinstance(result, str)
    assert "temporary" in result
    assert exchange_file.uri in result
    assert storage.put_calls == [("/tmp/agent/imports/report.csv", b"a,b\n1,2")]


@pytest.mark.asyncio
async def test_import_file_warns_for_explicit_tmp_path() -> None:
    """Explicit /tmp destination also returns transient warning."""
    storage = FakeSharedStorage()
    exchange_file = _make_exchange_file()
    service = AsyncMock()
    service.resolve_attachment.return_value = Success(
        ExchangeFileDownload(file=exchange_file, body=b"a,b\n1,2")
    )
    tool = make_import_file_tool(
        session_storage=storage,
        exchange_file_service=service,
        artifact_service=_make_artifact_service(),
        vfs_projection_service=None,
        session_id="session-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        run_id="run-1",
        user_id="user-1",
    )

    result = await tool.handler(
        json.dumps({"uri": exchange_file.uri, "path": "/tmp/report.csv"})
    )

    assert isinstance(result, str)
    assert "temporary" in result
    assert storage.put_calls == [("/tmp/report.csv", b"a,b\n1,2")]


@pytest.mark.asyncio
async def test_import_file_reports_missing_exchange_file() -> None:
    """Propagate Exchange file lookup failure as tool error."""
    storage = FakeSharedStorage()
    service = AsyncMock()
    service.resolve_attachment.return_value = Failure(FileNotFound())
    tool = make_import_file_tool(
        session_storage=storage,
        exchange_file_service=service,
        artifact_service=_make_artifact_service(),
        vfs_projection_service=None,
        session_id="session-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        run_id="run-1",
        user_id="user-1",
    )

    with pytest.raises(FunctionToolError, match="File not found"):
        await tool.handler(
            json.dumps({"uri": "exchange://exchange/workspace-1/uploads/a/original"})
        )


@pytest.mark.asyncio
async def test_import_file_allows_arbitrary_absolute_destination() -> None:
    """Absolute path destination is allowed without fixed prefix limit."""
    storage = FakeSharedStorage()
    exchange_file = _make_exchange_file()
    service = AsyncMock()
    service.resolve_attachment.return_value = Success(
        ExchangeFileDownload(file=exchange_file, body=b"a,b\n1,2")
    )
    tool = make_import_file_tool(
        session_storage=storage,
        exchange_file_service=service,
        artifact_service=_make_artifact_service(),
        vfs_projection_service=None,
        session_id="session-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        run_id="run-1",
        user_id="user-1",
    )

    result = await tool.handler(
        json.dumps(
            {
                "uri": exchange_file.uri,
                "path": "/var/report.csv",
            }
        )
    )

    assert isinstance(result, str)
    assert "/var/report.csv" in result
    assert storage.put_calls == [("/var/report.csv", b"a,b\n1,2")]


@pytest.mark.asyncio
async def test_import_file_writes_artifact_body_to_runtime() -> None:
    """Store Artifact bytes to runtime destination."""
    storage = FakeSharedStorage()
    exchange_service = AsyncMock()
    artifact = _make_artifact()
    artifact_service = AsyncMock()
    artifact_service.resolve.return_value = Success(
        ArtifactDownload(artifact=artifact, body=b"hello world")
    )
    tool = make_import_file_tool(
        session_storage=storage,
        exchange_file_service=exchange_service,
        artifact_service=artifact_service,
        vfs_projection_service=None,
        session_id="session-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        run_id="run-1",
        user_id="user-1",
    )

    result = await tool.handler(json.dumps({"uri": artifact.uri}))

    assert isinstance(result, str)
    assert "artifact://" in result
    assert storage.put_calls == [("/tmp/agent/imports/artifact.txt", b"hello world")]


@pytest.mark.asyncio
async def test_import_file_dedupes_default_destination() -> None:
    """Add suffix on default destination collision."""
    storage = FakeSharedStorage({"/tmp/agent/imports/report.csv": b"old"})
    exchange_file = _make_exchange_file()
    service = AsyncMock()
    service.resolve_attachment.return_value = Success(
        ExchangeFileDownload(file=exchange_file, body=b"a,b\n1,2")
    )
    tool = make_import_file_tool(
        session_storage=storage,
        exchange_file_service=service,
        artifact_service=_make_artifact_service(),
        vfs_projection_service=None,
        session_id="session-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        run_id="run-1",
        user_id="user-1",
    )

    await tool.handler(json.dumps({"uri": exchange_file.uri}))

    assert storage.put_calls == [("/tmp/agent/imports/report-1.csv", b"a,b\n1,2")]


@pytest.mark.asyncio
async def test_import_file_fails_explicit_destination_conflict() -> None:
    """Explicit destination collision fails without overwrite."""
    storage = FakeSharedStorage({"/workspace/agent/report.csv": b"old"})
    exchange_file = _make_exchange_file()
    service = AsyncMock()
    service.resolve_attachment.return_value = Success(
        ExchangeFileDownload(file=exchange_file, body=b"a,b\n1,2")
    )
    tool = make_import_file_tool(
        session_storage=storage,
        exchange_file_service=service,
        artifact_service=_make_artifact_service(),
        vfs_projection_service=None,
        session_id="session-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        run_id="run-1",
        user_id="user-1",
    )

    with pytest.raises(FunctionToolError, match="File already exists"):
        await tool.handler(
            json.dumps(
                {
                    "uri": exchange_file.uri,
                    "path": "/workspace/agent/report.csv",
                }
            )
        )


@pytest.mark.asyncio
async def test_import_file_writes_current_run_vfs_resource() -> None:
    """Materialize one verified azents:// resource through the existing path."""
    storage = FakeSharedStorage()
    service = _VfsService()
    uri = "azents://skills/test/sample/references/checklist.md"
    tool = make_import_file_tool(
        session_storage=storage,
        exchange_file_service=AsyncMock(),
        artifact_service=AsyncMock(),
        vfs_projection_service=service,  # pyright: ignore[reportArgumentType]
        session_id="session-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        run_id="run-1",
        user_id="user-1",
    )

    result = await tool.handler(json.dumps({"uri": uri}))

    assert isinstance(result, str)
    assert "azents" in result
    assert uri in result
    assert storage.put_calls == [
        ("/tmp/agent/imports/checklist.md", b"# Evidence checklist")
    ]


@pytest.mark.asyncio
async def test_import_file_reports_expired_artifact() -> None:
    """Propagate expired Artifact access failure as tool error."""
    storage = FakeSharedStorage()
    artifact_service = AsyncMock()
    artifact_service.resolve.return_value = Failure(ArtifactExpired())
    tool = make_import_file_tool(
        session_storage=storage,
        exchange_file_service=AsyncMock(),
        artifact_service=artifact_service,
        vfs_projection_service=None,
        session_id="session-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        run_id="run-1",
        user_id="user-1",
    )

    with pytest.raises(FunctionToolError, match="no longer available"):
        await tool.handler(
            json.dumps({"uri": "artifact://artifacts/workspace-1/session-1/10/b"})
        )
