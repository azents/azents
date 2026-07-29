"""Workspace path helpers for Runtime Runner operations."""

from pathlib import Path


class Workspace:
    """Resolve operation paths against the Runner process filesystem."""

    def __init__(self, root: str) -> None:
        """Initialize the default workspace root."""
        if not root:
            raise ValueError("workspace root is required")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, raw_path: object) -> Path:
        """Resolve an absolute or workspace-relative path.

        Legacy Runner versions rejected paths outside ``self.root``. Runtime file
        tools now intentionally operate on absolute runtime filesystem paths, while
        relative paths still resolve under the default workspace root.
        """
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("path is required")
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return candidate.resolve(strict=False)

    def display_path(self, path: Path) -> str:
        """Return a stable absolute display path."""
        return str(path.resolve(strict=False))
