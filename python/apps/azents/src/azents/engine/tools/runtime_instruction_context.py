"""Shared runtime instruction-loading context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.runtime.transfer.present_file_publication import (
    PresentFilePublicationRequest,
)
from azents.runtime.transfer.runtime_to_provider import (
    RuntimeToProviderDeliveryExecutor,
)
from azents.runtime.transfer.server_to_runtime import (
    ServerToRuntimeTarget,
    ServerToRuntimeTransferRequest,
)
from azents.services.file_storage import FileStorage


class ServerToRuntimeTransferExecutor(Protocol):
    """Backend-only terminal-success transfer service."""

    async def transfer(self, request: ServerToRuntimeTransferRequest) -> None:
        """Deliver one source and return only after Runtime commit success."""
        ...


class PresentFilePublicationExecutor(Protocol):
    """Backend-only managed publication service for Runtime file output."""

    async def publish(self, request: PresentFilePublicationRequest) -> ExchangeFile:
        """Publish one Runtime file to user-visible Exchange storage."""
        ...


RuntimeTargetResolver = Callable[[], Awaitable[ServerToRuntimeTarget]]


@dataclass(frozen=True)
class RuntimeInstructionContext:
    """Runtime file context shared by instruction appendix providers."""

    file_storage: FileStorage
    workspace_root: str | None
    projects: tuple[SessionWorkspaceProject, ...]
    transfer_service: ServerToRuntimeTransferExecutor
    publication_service: PresentFilePublicationExecutor
    provider_delivery_service: RuntimeToProviderDeliveryExecutor
    resolve_runtime_target: RuntimeTargetResolver


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
