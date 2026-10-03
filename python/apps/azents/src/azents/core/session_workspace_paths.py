"""Pure Runner-rooted Session Workspace path policy."""

import dataclasses
import posixpath
from pathlib import PurePosixPath


@dataclasses.dataclass(frozen=True)
class InvalidProjectPath:
    """Project path does not satisfy Session Workspace contract."""

    path: str
    reason: str


def normalize_agent_workspace_root(workspace_root: str | None) -> PurePosixPath:
    """Normalize the Runner-reported Agent Workspace root."""
    if workspace_root is None or not workspace_root.strip():
        raise ValueError("Agent Workspace path is unavailable")
    normalized = PurePosixPath(posixpath.normpath(workspace_root.strip()))
    if not normalized.is_absolute():
        raise ValueError("Agent Workspace path must be absolute")
    return normalized


def normalize_session_workspace_path(
    path: str,
    *,
    workspace_root: str,
) -> str:
    """Normalize absolute path inside Session Workspace.

    :param path: Path to validate
    :return: Normalized POSIX absolute path
    :raises ValueError: When path is empty, relative, root, or outside prefix
    """
    stripped = path.strip()
    if not stripped:
        raise ValueError("Project path is required")
    pure = PurePosixPath(posixpath.normpath(stripped))
    if not pure.is_absolute():
        raise ValueError("Project path must be absolute")
    normalized = PurePosixPath("/") / pure.relative_to("/")
    root = normalize_agent_workspace_root(workspace_root)
    if normalized == root:
        raise ValueError("Session Workspace root cannot be a Project")
    if not normalized.is_relative_to(root):
        raise ValueError("Project path must be under Agent Workspace root")
    return normalized.as_posix()


def normalize_session_workspace_project_paths(
    paths: list[str],
    *,
    workspace_root: str,
) -> list[str]:
    """Normalize Project paths and remove exact duplicates while preserving order."""
    normalized_paths: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = normalize_session_workspace_path(
            path,
            workspace_root=workspace_root,
        )
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_paths.append(normalized)
    return normalized_paths
