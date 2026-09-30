"""Trusted Runtime Workspace browser-download capability consumer."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from azcommon.infra.s3.service import S3Service, s3_checksum_matches_sha256
from azcommon.uuid import uuid7

from azents.runtime.transfer.present_file_publication import (
    OpaqueTransferObjectResolver,
)
from azents.runtime.transfer.runtime_to_server import (
    RuntimeToServerPublicationCallback,
    RuntimeToServerTransferRequest,
    VerifiedRuntimeUpload,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.services.browser_file_download import (
    BROWSER_DOWNLOAD_TICKET_TTL,
    BrowserFileDownloadTicket,
)


class WorkspaceDownloadError(RuntimeError):
    """Raised when an authorized Workspace GET capability cannot be issued."""


class RuntimeToServerTransferExecutor(Protocol):
    """Execute one opaque Runtime-to-server transfer and feature handoff."""

    async def transfer(self, request: RuntimeToServerTransferRequest) -> None:
        """Complete one verified Runtime upload consumer."""
        ...


@dataclass(frozen=True)
class WorkspaceDownloadRequest:
    """One authorized Agent Workspace file download."""

    agent_id: str
    runtime_path: str
    expected_size: int
    target: ServerToRuntimeTarget
    filename: str
    media_type: str


class _TicketCallback(RuntimeToServerPublicationCallback):
    """Issue a GET within the transfer-owned source retention deadline."""

    def __init__(
        self,
        *,
        resolver: OpaqueTransferObjectResolver,
        s3_service: S3Service,
        request: WorkspaceDownloadRequest,
        deadline_at: datetime.datetime,
        clock: Callable[[], datetime.datetime],
    ) -> None:
        self.resolver = resolver
        self.s3_service = s3_service
        self.request = request
        self.deadline_at = deadline_at
        self.clock = clock
        self.ticket: BrowserFileDownloadTicket | None = None

    async def publish(self, upload: VerifiedRuntimeUpload) -> None:
        """Publish a capability, never claim to observe browser EOF."""
        source = self.resolver.resolve(upload.object_handle.value)
        metadata = await self.s3_service.head_with_checksum(source)
        if (
            metadata is None
            or metadata.content_length != upload.size
            or (
                metadata.checksum_sha256 is not None
                and not s3_checksum_matches_sha256(
                    metadata.checksum_sha256, upload.sha256
                )
            )
        ):
            raise WorkspaceDownloadError("Verified Runtime file object is unavailable")
        current = self.clock()
        seconds = int(
            min(BROWSER_DOWNLOAD_TICKET_TTL, self.deadline_at - current).total_seconds()
        )
        if seconds <= 0:
            raise WorkspaceDownloadError("Workspace download ticket deadline expired")
        ticket = await self.s3_service.get_download_request(
            identity=source,
            expires_in=datetime.timedelta(seconds=seconds),
            now=current,
            filename=self.request.filename,
            content_type=self.request.media_type,
            inline=False,
        )
        self.ticket = BrowserFileDownloadTicket(
            url=ticket.url, expires_at=ticket.expires_at
        )


class RuntimeWorkspaceDownloadService:
    """Hand off an authorized GET capability for a verified temporary source."""

    def __init__(
        self,
        *,
        transfer_service: RuntimeToServerTransferExecutor,
        resolver: OpaqueTransferObjectResolver,
        s3_service: S3Service,
        product_maximum_size: int,
        deadline: datetime.timedelta,
        clock: Callable[[], datetime.datetime],
    ) -> None:
        self.transfer_service = transfer_service
        self.resolver = resolver
        self.s3_service = s3_service
        self.product_maximum_size = product_maximum_size
        self.deadline = deadline
        self.clock = clock

    async def create_download_ticket(
        self, request: WorkspaceDownloadRequest
    ) -> BrowserFileDownloadTicket:
        """Settle ticket handoff; cleanup waits for deadline plus read grace.

        Direct PUT coordination retains the immutable owned source until the
        maximum of its PUT capability expiry and operation deadline, plus the
        bounded read grace. The GET expiry is constrained to that same deadline.
        Successful settlement records feature handoff, not browser consumption.
        """
        operation_id = f"workspace-download-{uuid7().hex}"
        deadline_at = self.clock() + self.deadline
        callback = _TicketCallback(
            resolver=self.resolver,
            s3_service=self.s3_service,
            request=request,
            deadline_at=deadline_at,
            clock=self.clock,
        )
        await self.transfer_service.transfer(
            RuntimeToServerTransferRequest(
                target=request.target,
                agent_id=request.agent_id,
                session_id=None,
                operation_id=operation_id,
                runtime_path=request.runtime_path,
                expected_size=request.expected_size,
                expected_sha256=None,
                product_maximum_size=self.product_maximum_size,
                provider_maximum_size=self.product_maximum_size,
                deadline_at=deadline_at,
                resource_class="workspace_download",
                publication_id=operation_id,
                callback=callback,
            )
        )
        if callback.ticket is None:
            raise WorkspaceDownloadError(
                "Runtime Workspace transfer completed without a download ticket"
            )
        return callback.ticket
