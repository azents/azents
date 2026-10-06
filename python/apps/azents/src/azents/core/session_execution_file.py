"""Current private files; exact applicability without version history."""

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class CurrentExecutionFile:
    path: str
    content: str
    writable: bool


@dataclass(frozen=True)
class ExecutionFileChange:
    path: str
    before: str | None
    after: str | None


class ExecutionFileConflict(ValueError):
    """Exact current content does not match the requested mutation."""


def require_execution_path(path: str) -> None:
    """Admit only canonical relative paths within this execution file domain."""
    if (
        not path
        or len(path) > 512
        or path.startswith("/")
        or any(character in path for character in "\\\x00\r\n:")
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or str(PurePosixPath(path)) != path
    ):
        raise ValueError("Private execution file path is invalid.")
    require_execution_text(path)


def require_execution_text(content: str) -> None:
    """Validate text before PostgreSQL or tool encoding can reject it."""
    if "\x00" in content:
        raise ValueError("Private execution files cannot contain NUL characters.")
    try:
        content.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("Private execution files require valid UTF-8 text.") from error
