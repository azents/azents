"""Shared runtime instruction-loading context."""

from __future__ import annotations

from dataclasses import dataclass

from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.services.file_storage import FileStorage


@dataclass(frozen=True)
class RuntimeInstructionContext:
    """Runtime file context shared by instruction appendix providers."""

    file_storage: FileStorage
    projects: tuple[SessionWorkspaceProject, ...]


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
