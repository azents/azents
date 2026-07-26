"""Workspace path helpers for Runtime Runner operations."""

import os
from pathlib import Path


class Workspace:
    """Resolve operation paths against the Runner process filesystem."""

    def __init__(self, root: str, *, blocked_paths: tuple[Path, ...] = ()) -> None:
        """Initialize the default workspace root."""
        if not root:
            raise ValueError("workspace root is required")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._blocked_paths = tuple(
            path.resolve(strict=False) for path in blocked_paths
        )

    def resolve(self, raw_path: object) -> Path:
        """Resolve an absolute or workspace-relative path.

        Legacy Runner versions rejected paths outside ``self.root``. Runtime file
        tools now intentionally operate on absolute runtime filesystem paths, while
        relative paths still resolve under the default workspace root.
        """
        candidate = self._absolute_path(raw_path)
        resolved = candidate.resolve(strict=False)
        self._reject_blocked(resolved)
        return resolved

    def resolve_lexical(self, raw_path: object) -> Path:
        """Return a normalized path while enforcing resolved blocked-path identity."""
        candidate = Path(os.path.normpath(str(self._absolute_path(raw_path))))
        self._reject_blocked(candidate.resolve(strict=False))
        return candidate

    def display_path(self, path: Path) -> str:
        """Return a stable absolute display path."""
        return str(path.resolve(strict=False))

    @property
    def has_blocked_paths(self) -> bool:
        """Return whether this Runner has a protected filesystem boundary."""
        return bool(self._blocked_paths)

    def _absolute_path(self, raw_path: object) -> Path:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("path is required")
        candidate = Path(raw_path)
        if candidate.is_absolute():
            return candidate
        return self.root / candidate

    def _reject_blocked(self, resolved: Path) -> None:
        if any(_is_within(resolved, blocked) for blocked in self._blocked_paths):
            raise ValueError("path is reserved for Runtime transfer staging")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
