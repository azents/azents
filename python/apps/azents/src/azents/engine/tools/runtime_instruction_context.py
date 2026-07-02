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
