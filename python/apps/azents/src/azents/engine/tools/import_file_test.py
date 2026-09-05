"""import_file Server-to-Runtime consumer tests."""

import datetime
import json
import logging
from unittest.mock import AsyncMock

import pytest
from azcommon.infra.s3.service import S3Service, S3TransferCleanupRequired
from azcommon.result import Failure, Success
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorTransferFailure,
)

from azents.core.enums import (
    ArtifactStatus,
    ExchangeFileOrigin,
    ExchangeFileProvenanceKind,
    ExchangeFileStatus,
)
from azents.core.vfs import make_vfs_projection, make_vfs_source_revision
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tools.import_file import (
    ImportFileStagingConfiguration,
    make_import_file_tool,
)
from azents.engine.tools.testing import FakeSharedStorage
from azents.repos.artifact.data import Artifact
from azents.repos.exchange_file.data import ExchangeFile
from azents.runtime.transfer.managed_source import ManagedServerToRuntimeSource
from azents.runtime.transfer.server_to_runtime import (
    ServerToRuntimeCoordinatorError,
    ServerToRuntimeTarget,
    ServerToRuntimeTransferAdmissionTimeout,
    ServerToRuntimeTransferConnectionTimeout,
    ServerToRuntimeTransferError,
    ServerToRuntimeTransferLimitExceeded,
    ServerToRuntimeTransferRequest,
)
from azents.runtime.transfer.vfs_source import VfsServerToRuntimeSource
from azents.services.artifact import ArtifactExpired, ArtifactTransferSource
from azents.services.exchange_file import ExchangeFileTransferSource, FileNotFound
from azents.services.session_resource_authority import SessionResourceAuthority
from azents.services.vfs import VfsResolvedFile

_NOW = datetime.datetime.now(datetime.timezone.utc)


class _TransferService:
    """Capture terminal-success import requests without legacy byte delivery."""

    def __init__(self, failure: Exception | None) -> None:
        self.failure = failure
        self.requests: list[ServerToRuntimeTransferRequest] = []

    async def transfer(self, request: ServerToRuntimeTransferRequest) -> None:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure


class _ReadOnlyStorage(FakeSharedStorage):
    """Storage double that rejects destination preflight access."""

    async def exists(
        self,
        path: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        del path, agent_id, user_id
        raise PermissionError("read-only")


async def _resolve_runtime_target() -> ServerToRuntimeTarget:
    return ServerToRuntimeTarget(runtime_id="runtime-1", desired_generation=2)


def _staging_configuration() -> ImportFileStagingConfiguration:
    return ImportFileStagingConfiguration(
        s3_service=object.__new__(S3Service),
        workspace_bucket="workspace",
        transfer_object_prefix="runtime-transfer",
        multipart_copy_threshold=5 * 1024 * 1024,
        multipart_part_size=5 * 1024 * 1024,
        maximum_size=16 * 1024 * 1024,
        deadline_after=datetime.timedelta(minutes=5),
    )


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

    async def resolve_transfer_file(
        self,
        *,
        run_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
        uri: str,
    ) -> VfsResolvedFile:
        """Return the fixture entry from the run projection."""
        del run_id, agent_id, session_id, workspace_id
        entry = self.projection.find(uri)
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
        size_bytes=4 * 1024 * 1024 + 1,
        sha256="0" * 64,
        provenance_kind=ExchangeFileProvenanceKind.HUMAN,
        source_user_id="user-1",
        source_agent_id=None,
        source_run_id=None,
        source_tool_name=None,
        source_provider=None,
        source_exchange_file_id=None,
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


def _tool(
    *,
    storage: FakeSharedStorage,
    exchange_file_service: AsyncMock,
    artifact_service: AsyncMock,
    vfs_projection_service: _VfsService | None,
    transfer_service: _TransferService,
) -> FunctionTool:
    """Construct import_file with the complete backend-only transfer seam."""
    return make_import_file_tool(
        session_storage=storage,
        exchange_file_service=exchange_file_service,
        artifact_service=artifact_service,
        vfs_projection_service=vfs_projection_service,
        authority=_authority(),
        transfer_service=transfer_service,
        resolve_runtime_target=_resolve_runtime_target,
        staging_configuration=_staging_configuration(),
    )


@pytest.mark.asyncio
async def test_import_file_stages_large_exchange_without_legacy_body_delivery() -> None:
    """Exchange imports build a managed source and return terminal-success copy."""
    storage = FakeSharedStorage()
    exchange_file = _make_exchange_file()
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=exchange_file)
    )
    transfer_service = _TransferService(None)
    tool = _tool(
        storage=storage,
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=transfer_service,
    )

    result = await tool.handler(json.dumps({"uri": exchange_file.uri}))

    assert isinstance(result, str)
    assert exchange_file.uri in result
    assert "exchange, text/csv, 4194305 bytes" in result
    assert "temporary" in result
    assert storage.put_calls == []
    request = transfer_service.requests[0]
    assert request.destination == "/tmp/agent/imports/report.csv"
    assert request.target == ServerToRuntimeTarget("runtime-1", 2)
    assert isinstance(request.source, ManagedServerToRuntimeSource)
    assert request.source.metadata.size == 4 * 1024 * 1024 + 1
    exchange_service.resolve_for_authority.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_file_stages_artifact_to_explicit_destination() -> None:
    """Artifact imports retain explicit path and use the managed source adapter."""
    storage = FakeSharedStorage()
    artifact = _make_artifact()
    artifact_service = AsyncMock()
    artifact_service.resolve_transfer_source_for_authority.return_value = Success(
        ArtifactTransferSource(artifact=artifact)
    )
    transfer_service = _TransferService(None)
    tool = _tool(
        storage=storage,
        exchange_file_service=AsyncMock(),
        artifact_service=artifact_service,
        vfs_projection_service=None,
        transfer_service=transfer_service,
    )

    result = await tool.handler(
        json.dumps({"uri": artifact.uri, "path": "/workspace/agent/artifact.txt"})
    )

    assert isinstance(result, str)
    assert artifact.uri in result
    assert storage.put_calls == []
    request = transfer_service.requests[0]
    assert request.destination == "/workspace/agent/artifact.txt"
    assert isinstance(request.source, ManagedServerToRuntimeSource)
    artifact_service.resolve_for_authority.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_file_stages_vfs_without_decode_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Current-run VFS imports retain the encoded entry for incremental staging."""
    storage = FakeSharedStorage()
    service = _VfsService()
    entry = service.projection.entries[0]
    monkeypatch.setattr(
        type(entry),
        "decode_body",
        lambda self: (_ for _ in ()).throw(AssertionError("eager decode")),
    )
    transfer_service = _TransferService(None)
    tool = _tool(
        storage=storage,
        exchange_file_service=AsyncMock(),
        artifact_service=AsyncMock(),
        vfs_projection_service=service,
        transfer_service=transfer_service,
    )

    result = await tool.handler(json.dumps({"uri": entry.canonical_uri}))

    assert isinstance(result, str)
    assert entry.canonical_uri in result
    assert storage.put_calls == []
    request = transfer_service.requests[0]
    assert isinstance(request.source, VfsServerToRuntimeSource)
    assert request.source.entry is entry


@pytest.mark.asyncio
async def test_import_file_dedupes_default_path_before_transfer() -> None:
    """Default destination dedupe remains an advisory preflight before admission."""
    exchange_file = _make_exchange_file()
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=exchange_file)
    )
    transfer_service = _TransferService(None)
    tool = _tool(
        storage=FakeSharedStorage({"/tmp/agent/imports/report.csv": b"old"}),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=transfer_service,
    )

    await tool.handler(json.dumps({"uri": exchange_file.uri}))

    assert transfer_service.requests[0].destination == "/tmp/agent/imports/report-1.csv"


@pytest.mark.asyncio
async def test_import_file_fails_explicit_destination_conflict_before_admission() -> (
    None
):
    """No transfer occurs for an explicit no-overwrite preflight conflict."""
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=_make_exchange_file())
    )
    transfer_service = _TransferService(None)
    tool = _tool(
        storage=FakeSharedStorage({"/workspace/agent/report.csv": b"old"}),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=transfer_service,
    )

    with pytest.raises(FunctionToolError, match="File already exists"):
        await tool.handler(
            json.dumps(
                {
                    "uri": "exchange://opaque",
                    "path": "/workspace/agent/report.csv",
                }
            )
        )

    exchange_service.resolve_transfer_source_for_authority.assert_awaited_once()
    assert transfer_service.requests == []


@pytest.mark.asyncio
async def test_import_file_maps_terminal_transfer_failure_to_tool_error() -> None:
    """A non-success terminal Runtime result never produces import success text."""
    exchange_file = _make_exchange_file()
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=exchange_file)
    )
    transfer_service = _TransferService(
        ServerToRuntimeTransferError(
            "Runtime transfer failed before destination commit"
        )
    )
    tool = _tool(
        storage=FakeSharedStorage(),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=transfer_service,
    )

    with pytest.raises(FunctionToolError, match="Failed to transfer imported file"):
        await tool.handler(json.dumps({"uri": exchange_file.uri}))

    assert len(transfer_service.requests) == 1


@pytest.mark.asyncio
async def test_import_file_reports_transfer_limit_error() -> None:
    """A source-size rejection must not be presented as a path failure."""
    exchange_file = _make_exchange_file()
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=exchange_file)
    )
    tool = _tool(
        storage=FakeSharedStorage(),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=_TransferService(
            ServerToRuntimeTransferLimitExceeded(
                "Transfer source exceeds configured limit"
            )
        ),
    )

    with pytest.raises(
        FunctionToolError,
        match="exceeds the configured Runtime transfer limit",
    ) as raised:
        await tool.handler(json.dumps({"uri": exchange_file.uri}))

    assert "absolute runtime paths" not in str(raised.value)


@pytest.mark.asyncio
async def test_import_file_reports_admission_timeout() -> None:
    """Bounded admission waiting reports capacity timeout without path advice."""
    exchange_file = _make_exchange_file()
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=exchange_file)
    )
    tool = _tool(
        storage=FakeSharedStorage(),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=_TransferService(
            ServerToRuntimeTransferAdmissionTimeout(
                "Runtime transfer admission remained unavailable until deadline",
                failure=CoordinatorTransferFailure.ADMISSION,
            )
        ),
    )

    with pytest.raises(
        FunctionToolError,
        match="capacity remained unavailable until the import deadline",
    ) as raised:
        await tool.handler(json.dumps({"uri": exchange_file.uri}))

    assert "absolute runtime paths" not in str(raised.value)


@pytest.mark.asyncio
async def test_import_file_reports_coordinator_connection_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Bounded connection recovery reports its own timeout category."""
    exchange_file = _make_exchange_file()
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=exchange_file)
    )
    tool = _tool(
        storage=FakeSharedStorage(),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=_TransferService(
            ServerToRuntimeTransferConnectionTimeout(
                "Runtime transfer coordinator connection timed out",
                failure=CoordinatorTransferFailure.STREAM,
            )
        ),
    )

    with (
        caplog.at_level(
            logging.ERROR,
            logger="azents.engine.tools.import_file",
        ),
        pytest.raises(
            FunctionToolError,
            match="connection remained unavailable until the import deadline",
        ) as raised,
    ):
        await tool.handler(json.dumps({"uri": exchange_file.uri}))

    assert "capacity" not in str(raised.value)
    record = caplog.records[-1]
    assert record.__dict__["transfer_phase"] == "admission"
    assert record.__dict__["transfer_failure"] == "stream"
    assert record.exc_info is not None


@pytest.mark.asyncio
async def test_import_file_logs_coordinator_failure_phase(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Coordinator failures retain phase and exception evidence in logs."""
    exchange_file = _make_exchange_file()
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=exchange_file)
    )
    tool = _tool(
        storage=FakeSharedStorage(),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=_TransferService(
            ServerToRuntimeCoordinatorError(
                "Runtime transfer coordinator request failed",
                phase="dispatch",
                failure=CoordinatorTransferFailure.FENCED,
            )
        ),
    )

    with (
        caplog.at_level(
            logging.ERROR,
            logger="azents.engine.tools.import_file",
        ),
        pytest.raises(FunctionToolError, match="Runtime changed while importing"),
    ):
        await tool.handler(json.dumps({"uri": exchange_file.uri}))

    record = caplog.records[-1]
    assert record.__dict__["transfer_phase"] == "dispatch"
    assert record.__dict__["transfer_failure"] == "fenced"
    assert record.exc_info is not None


@pytest.mark.asyncio
async def test_import_file_logs_classified_terminal_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Terminal failures retain classification and exception evidence in logs."""
    exchange_file = _make_exchange_file()
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=exchange_file)
    )
    tool = _tool(
        storage=FakeSharedStorage(),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=_TransferService(
            ServerToRuntimeTransferError(
                "Runtime transfer failed before destination commit",
                failure=CoordinatorTransferFailure.INTEGRITY,
            )
        ),
    )

    with (
        caplog.at_level(
            logging.ERROR,
            logger="azents.engine.tools.import_file",
        ),
        pytest.raises(FunctionToolError, match="integrity verification failed"),
    ):
        await tool.handler(json.dumps({"uri": exchange_file.uri}))

    record = caplog.records[-1]
    assert record.__dict__["transfer_phase"] == "terminal"
    assert record.__dict__["transfer_failure"] == "integrity"
    assert record.exc_info is not None


@pytest.mark.asyncio
async def test_import_file_preserves_read_only_and_staging_error_contracts() -> None:
    """Expected destination and staging failures remain controlled tool errors."""
    exchange_file = _make_exchange_file()
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=exchange_file)
    )
    read_only_tool = _tool(
        storage=_ReadOnlyStorage(),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=_TransferService(None),
    )
    with pytest.raises(FunctionToolError, match="read-only scope"):
        await read_only_tool.handler(
            json.dumps(
                {
                    "uri": exchange_file.uri,
                    "path": "/workspace/agent/report.csv",
                }
            )
        )

    staging_tool = _tool(
        storage=FakeSharedStorage(),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=_TransferService(
            S3TransferCleanupRequired(
                "bucket/internal-key must remain hidden",
                multipart_cleanup_required=True,
                completed_object_cleanup_required=False,
            )
        ),
    )
    with pytest.raises(FunctionToolError, match="prepare imported file"):
        await staging_tool.handler(json.dumps({"uri": exchange_file.uri}))

    invalid_staging_tool = _tool(
        storage=FakeSharedStorage(),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=_TransferService(
            ValueError("internal transfer key hash does not match")
        ),
    )
    with pytest.raises(
        FunctionToolError,
        match="integrity verification failed",
    ) as raised:
        await invalid_staging_tool.handler(json.dumps({"uri": exchange_file.uri}))
    assert "internal transfer key" not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            ServerToRuntimeTransferError(
                "Runtime transfer cancelled",
                failure=CoordinatorTransferFailure.CANCELLED,
            ),
            "cancelled before destination commit",
        ),
        (
            ServerToRuntimeTransferError(
                "Runtime transfer expired",
                failure=CoordinatorTransferFailure.EXPIRED,
            ),
            "did not complete before its deadline",
        ),
        (
            ServerToRuntimeTransferError(
                "Runtime transfer integrity failure",
                failure=CoordinatorTransferFailure.INTEGRITY,
            ),
            "integrity verification failed",
        ),
        (
            ServerToRuntimeTransferError(
                "Runtime transfer destination failure",
                failure=CoordinatorTransferFailure.CONSUMER,
            ),
            "destination is not writable",
        ),
        (
            ServerToRuntimeTransferError(
                "Transfer source authority changed before dispatch"
            ),
            "Session resource authority changed",
        ),
        (
            ServerToRuntimeTransferError(
                "Runtime transfer admission failed",
                failure=CoordinatorTransferFailure.ADMISSION,
            ),
            "capacity is temporarily unavailable",
        ),
        (
            ServerToRuntimeTransferError(
                "Runtime transfer was fenced",
                failure=CoordinatorTransferFailure.FENCED,
            ),
            "Runtime changed while importing",
        ),
        (
            ServerToRuntimeTransferError(
                "Runtime transfer stream failed",
                failure=CoordinatorTransferFailure.STREAM,
            ),
            "connection is unavailable",
        ),
        (
            ServerToRuntimeTransferError("Unclassified transfer failure"),
            "Failed to transfer imported file to Runtime",
        ),
    ],
)
async def test_import_file_maps_bounded_transfer_failures(
    error: ServerToRuntimeTransferError,
    message: str,
) -> None:
    """Terminal and authority outcomes retain feature-specific safe messages."""
    exchange_file = _make_exchange_file()
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=exchange_file)
    )
    tool = _tool(
        storage=FakeSharedStorage(),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=_TransferService(error),
    )

    with pytest.raises(FunctionToolError, match=message):
        await tool.handler(json.dumps({"uri": exchange_file.uri}))


@pytest.mark.asyncio
async def test_import_file_preserves_exchange_and_artifact_resolution_errors() -> None:
    """Metadata resolver errors retain their existing feature-level messages."""
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Failure(
        FileNotFound()
    )
    transfer_service = _TransferService(None)
    exchange_tool = _tool(
        storage=FakeSharedStorage(),
        exchange_file_service=exchange_service,
        artifact_service=AsyncMock(),
        vfs_projection_service=None,
        transfer_service=transfer_service,
    )
    with pytest.raises(FunctionToolError, match="File not found"):
        await exchange_tool.handler(json.dumps({"uri": "exchange://missing"}))

    artifact_service = AsyncMock()
    artifact_service.resolve_transfer_source_for_authority.return_value = Failure(
        ArtifactExpired()
    )
    artifact_tool = _tool(
        storage=FakeSharedStorage(),
        exchange_file_service=AsyncMock(),
        artifact_service=artifact_service,
        vfs_projection_service=None,
        transfer_service=transfer_service,
    )
    with pytest.raises(FunctionToolError, match="no longer available"):
        await artifact_tool.handler(json.dumps({"uri": "artifact://expired"}))
    assert transfer_service.requests == []


def _authority() -> SessionResourceAuthority:
    """Create canonical Session/Run authority for tests."""
    return SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="session-1",
        run_id="run-1",
        run_index=10,
        owner_generation=1,
    )
