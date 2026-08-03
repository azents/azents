"""Session working-folder path policy."""

from pathlib import PurePosixPath

SESSION_WORKING_FOLDER_ROOT = PurePosixPath("/workspace/agent/.azents/sessions")


def build_session_working_folder_path(root_session_handle: str) -> str:
    """Build the canonical working-folder path for a root Session."""
    if (
        not root_session_handle
        or root_session_handle in {".", ".."}
        or PurePosixPath(root_session_handle).name != root_session_handle
    ):
        raise ValueError("Root Session handle is not a valid path component")
    return str(SESSION_WORKING_FOLDER_ROOT / root_session_handle)


def validate_session_working_folder_path(path: str) -> str:
    """Validate and return one canonical managed Session working-folder path."""
    candidate = PurePosixPath(path)
    if (
        not candidate.is_absolute()
        or str(candidate) != path
        or candidate.parent != SESSION_WORKING_FOLDER_ROOT
        or candidate.name in {"", ".", ".."}
    ):
        raise ValueError("Session working-folder path is outside the managed root")
    return path
