"""Shared runtime instruction-loading context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.runtime.transfer.server_to_runtime import (
    ServerToRuntimeTarget,
    ServerToRuntimeTransferRequest,
)
from azents.services.file_storage import FileStorage


class ServerToRuntimeTransferExecutor(Protocol):
    """Backend-only terminal-success transfer service capability."""

    async def transfer(self, request: ServerToRuntimeTransferRequest) -> None:
        """Deliver one source and return only after Runtime commit success."""
        ...


@dataclass(frozen=True)
class RuntimeTransferCapability:
    """Current Runtime transfer identity and an injected backend service."""

    service: ServerToRuntimeTransferExecutor
    target: ServerToRuntimeTarget


@dataclass(frozen=True)
class RuntimeInstructionContext:
    """Runtime file context shared by instruction appendix providers."""

    file_storage: FileStorage
    projects: tuple[SessionWorkspaceProject, ...]
    transfer_capability: RuntimeTransferCapability | None


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
