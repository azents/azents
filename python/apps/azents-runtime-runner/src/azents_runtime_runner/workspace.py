"""Workspace path resolution for Runtime Runner operations."""

import os
from pathlib import Path


class Workspace:
    """Resolve operation paths against one Runtime workspace."""

    def __init__(self, root: str) -> None:
        """Initialize the default workspace root."""
        if not root:
            raise ValueError("workspace root is required")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, raw_path: object, *, write: bool = False) -> Path:
        """Resolve a path for a native operation."""
        del write
        return self._logical_path(raw_path).resolve(strict=False)

    def resolve_lexical(self, raw_path: object, *, write: bool = False) -> Path:
        """Resolve without following the final path component."""
        del write
        path = self._logical_path(raw_path)
        path.parent.resolve(strict=False)
        return path

    def resolve_process_directory(self, raw_path: object) -> Path:
        """Resolve a process directory and preserve its logical spelling."""
        logical = self._logical_path(raw_path)
        if not logical.resolve(strict=False).is_dir():
            raise ValueError(f"No such directory: {logical}")
        return logical

    def display_path(self, path: Path) -> str:
        """Return the resolved Runtime-visible path."""
        return str(path.resolve(strict=False))

    def display_lexical_path(self, path: Path) -> str:
        """Return a Runtime-visible path without following its final component."""
        return str(path)

    def resolved_symlink_target(self, path: Path) -> Path | None:
        """Return a symlink target when it can be resolved."""
        return path.resolve(strict=False)

    def _logical_path(self, raw_path: object) -> Path:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("path is required")
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.root / path
        return Path(os.path.normpath(str(path)))
