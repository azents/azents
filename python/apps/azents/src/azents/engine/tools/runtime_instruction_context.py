"""Shared runtime instruction-loading context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.runtime.transfer.present_file_publication import (
    PresentFilePublicationRequest,
)
from azents.runtime.transfer.runtime_to_provider import (
    RuntimeToProviderDeliveryCapability,
)
from azents.runtime.transfer.server_to_runtime import (
    ServerToRuntimeTarget,
    ServerToRuntimeTransferRequest,
)
from azents.services.file_storage import FileStorage
from azents.services.session_resource_authority import SessionResourceAuthority


class ServerToRuntimeTransferExecutor(Protocol):
    """Backend-only terminal-success transfer service capability."""

    async def transfer(self, request: ServerToRuntimeTransferRequest) -> None:
        """Deliver one source and return only after Runtime commit success."""
        ...


class PresentFilePublicationExecutor(Protocol):
    """Backend-only managed publication capability for Runtime file output."""

    async def publish(self, request: PresentFilePublicationRequest) -> ExchangeFile:
        """Publish one Runtime file to user-visible Exchange storage."""
        ...


@dataclass(frozen=True)
class RuntimeTransferCapability:
    """Current Runtime transfer identity and an injected backend service."""

    service: ServerToRuntimeTransferExecutor
    target: ServerToRuntimeTarget


class RuntimeToServerPublicationCapability:
    """Expose Runtime publication operations without storage implementation data."""

    def __init__(
        self,
        *,
        service: PresentFilePublicationExecutor,
        target: ServerToRuntimeTarget,
    ) -> None:
        """Bind one trusted publication operation to the selected Runtime."""
        self._service = service
        self.target = target

    async def publish(
        self,
        *,
        runtime_path: str,
        filename: str,
        media_type: str,
        expected_size: int,
        authority: SessionResourceAuthority,
        publication_id: str,
    ) -> ExchangeFile:
        """Publish one Runtime file after final managed transfer settlement."""
        return await self._service.publish(
            PresentFilePublicationRequest(
                runtime_path=runtime_path,
                filename=filename,
                media_type=media_type,
                expected_size=expected_size,
                authority=authority,
                target=self.target,
                publication_id=publication_id,
            )
        )


@dataclass(frozen=True)
class RuntimeInstructionContext:
    """Runtime file context shared by instruction appendix providers."""

    file_storage: FileStorage
    projects: tuple[SessionWorkspaceProject, ...]
    transfer_capability: RuntimeTransferCapability | None
    publication_capability: RuntimeToServerPublicationCapability | None
    provider_delivery_capability: RuntimeToProviderDeliveryCapability | None


class RuntimeInstructionContextStore:
    """Mutable per-run holder for shared runtime instruction context."""

    def __init__(self) -> None:
        """Create an empty Runtime instruction context store."""
        self._context: RuntimeInstructionContext | None = None

    def set(self, context: RuntimeInstructionContext) -> None:
        """Store latest Runtime instruction context."""
        self._context = context

    def get(self) -> RuntimeInstructionContext | None:
        """Return latest Runtime instruction context if available."""
        return self._context
