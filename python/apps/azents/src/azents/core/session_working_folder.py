"""Session working-folder path policy."""

from pathlib import PurePosixPath


def build_session_working_folder_path(
    root_session_handle: str,
    *,
    workspace_root: str,
) -> str:
    """Build the canonical working-folder path for a root Session."""
    if (
        not root_session_handle
        or root_session_handle in {".", ".."}
        or PurePosixPath(root_session_handle).name != root_session_handle
    ):
        raise ValueError("Root Session handle is not a valid path component")
    return str(_session_working_folder_root(workspace_root) / root_session_handle)


def validate_session_working_folder_path(
    path: str,
    *,
    workspace_root: str,
) -> str:
    """Validate and return one canonical managed Session working-folder path."""
    candidate = PurePosixPath(path)
    session_working_folder_root = _session_working_folder_root(workspace_root)
    if (
        not candidate.is_absolute()
        or str(candidate) != path
        or candidate.parent != session_working_folder_root
        or candidate.name in {"", ".", ".."}
    ):
        raise ValueError("Session working-folder path is outside the managed root")
    return path


def _session_working_folder_root(workspace_root: str) -> PurePosixPath:
    """Return the managed Session-folder root below one Runner workspace."""
    candidate = PurePosixPath(workspace_root)
    if not candidate.is_absolute() or str(candidate) != workspace_root:
        raise ValueError("Agent Workspace root is not an absolute canonical path")
    return candidate / ".azents" / "sessions"
