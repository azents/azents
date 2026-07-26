"""Tests for server-only present-file publication adapter."""

import datetime
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from azcommon.infra.s3.service import S3ObjectIdentity
from azcommon.result import Failure, Success
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorOpaqueObjectHandle,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.core.enums import (
    ExchangeFileOrigin,
    ExchangeFileProvenanceKind,
    ExchangeFileStatus,
)
from azents.repos.exchange_file.data import ExchangeFile
from azents.runtime.transfer.present_file_publication import (
    PresentFilePublicationRequest,
    PresentFilePublicationService,
    RuntimeTransferObjectResolver,
)
from azents.runtime.transfer.runtime_to_server import (
    RuntimeToServerTransferRequest,
    VerifiedRuntimeUpload,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.services.exchange_file import FileAccessDenied
from azents.services.session_resource_authority import SessionResourceAuthority

_NOW = datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC)


class _Resolver:
    def __init__(self) -> None:
        self.handles: list[str] = []

    def resolve(self, opaque_handle: str) -> S3ObjectIdentity:
        self.handles.append(opaque_handle)
        return S3ObjectIdentity(bucket="private", key=f"private/{opaque_handle}")


@dataclass
class _Transfer:
    requests: list[RuntimeToServerTransferRequest] = field(default_factory=list)

    async def transfer(self, request: RuntimeToServerTransferRequest) -> None:
        """Publish one verified upload through the feature callback."""
        self.requests.append(request)
        await request.callback.publish(
            VerifiedRuntimeUpload(
                identity=CoordinatorTransferIdentity(
                    transfer_id="transfer",
                    attempt_id="attempt",
                    runtime_id="runtime",
                    desired_generation=1,
                    direction="upload",
                    operation_id="operation",
                    session_id="session",
                    agent_id="agent",
                ),
                publication_id=request.publication_id,
                object_handle=CoordinatorOpaqueObjectHandle("opaque-handle"),
                size=7,
                sha256="a" * 64,
            )
        )


def _request() -> PresentFilePublicationRequest:
    return PresentFilePublicationRequest(
        runtime_path="/workspace/agent/report.txt",
        filename="report.txt",
        media_type="text/plain",
        expected_size=7,
        authority=SessionResourceAuthority(
            workspace_id="workspace",
            agent_id="agent",
            session_id="session",
            root_session_id="session",
            run_id="run",
            run_index=1,
            owner_generation=1,
        ),
        target=ServerToRuntimeTarget(runtime_id="runtime", desired_generation=1),
        publication_id="stable-id",
    )


def _file() -> ExchangeFile:
    return ExchangeFile(
        id="file",
        workspace_id="workspace",
        agent_id="agent",
        origin_type=ExchangeFileOrigin.ARTIFACT,
        status=ExchangeFileStatus.AVAILABLE,
        object_key="exchange/workspace/files/file/original",
        filename="report.txt",
        media_type="text/plain",
        size_bytes=7,
        sha256="a" * 64,
        provenance_kind=ExchangeFileProvenanceKind.TOOL,
        source_user_id=None,
        source_agent_id=None,
        source_run_id="run",
        source_tool_name="present_file",
        source_provider=None,
        source_exchange_file_id=None,
        retention_root_session_id="session",
        retention_bound_at=_NOW,
        preview_thumbnail_file_id=None,
        preview_thumbnail_uri=None,
        preview_title=None,
        preview_summary=None,
        preview_thumbnail_media_type=None,
        preview_thumbnail_width=None,
        preview_thumbnail_height=None,
        preview_generated_at=None,
        expires_at=_NOW + datetime.timedelta(days=7),
        expired_at=None,
        blob_deleted_at=None,
        created_at=_NOW,
    )


def _service(
    transfer: _Transfer,
    resolver: _Resolver,
    exchange: AsyncMock,
) -> PresentFilePublicationService:
    return PresentFilePublicationService(
        transfer_service=transfer,
        resolver=resolver,
        exchange_file_service=exchange,
        product_maximum_size=10,
        provider_maximum_size=10,
        deadline=datetime.timedelta(minutes=1),
    )


@pytest.mark.asyncio
async def test_adapter_resolves_handle_and_returns_commit() -> None:
    """Publish only after resolving a verified opaque object handle privately."""
    transfer = _Transfer()
    resolver = _Resolver()
    exchange = AsyncMock()
    exchange.create_from_verified_object_for_authority.return_value = Success(_file())

    result = await _service(transfer, resolver, exchange).publish(_request())

    assert result.id == "file"
    assert resolver.handles == ["opaque-handle"]
    assert transfer.requests[0].publication_id == "stable-id"
    assert "private" not in repr(transfer.requests[0])
    exchange.create_from_verified_object_for_authority.assert_awaited_once_with(
        authority=_request().authority,
        source=S3ObjectIdentity(bucket="private", key="private/opaque-handle"),
        size_bytes=7,
        sha256="a" * 64,
        publication_id="stable-id",
        provenance_kind=ExchangeFileProvenanceKind.TOOL,
        source_tool_name="present_file",
        source_provider=None,
        filename="report.txt",
        media_type="text/plain",
    )


@pytest.mark.asyncio
async def test_adapter_propagates_authority_failure_without_committed_result() -> None:
    """Raise so the transfer abandons an uncommitted product publication."""
    transfer = _Transfer()
    exchange = AsyncMock()
    exchange.create_from_verified_object_for_authority.return_value = Failure(
        FileAccessDenied()
    )

    with pytest.raises(RuntimeError, match="denied"):
        await _service(transfer, _Resolver(), exchange).publish(_request())


def test_runtime_transfer_object_resolver_resolves_server_side() -> None:
    """Translate an opaque handle only through trusted bucket and prefix config."""
    resolver = RuntimeTransferObjectResolver(
        bucket="transfer-bucket",
        object_prefix="/runtime/transfers/",
    )

    assert resolver.resolve("opaque-handle") == S3ObjectIdentity(
        bucket="transfer-bucket",
        key="runtime/transfers/opaque-handle",
    )
