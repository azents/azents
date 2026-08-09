"""Workspace path authorization for Runtime Runner operations."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_LOGICAL_TEMPORARY_ROOT = Path("/tmp")


@dataclass(frozen=True)
class FilesystemAccessPolicy:
    """Common filesystem authority enforced by shell and native operations."""

    restricted: bool
    temporary_backing_path: Path | None
    read_only_paths: tuple[Path, ...]
    denied_paths: tuple[Path, ...]

    @classmethod
    def unrestricted(cls) -> FilesystemAccessPolicy:
        """Return the direct-Profile filesystem authority."""
        return cls(
            restricted=False,
            temporary_backing_path=None,
            read_only_paths=(),
            denied_paths=(),
        )

    @classmethod
    def contained(
        cls,
        *,
        temporary_backing_path: Path,
        read_only_paths: Sequence[Path],
        denied_paths: Sequence[Path],
    ) -> FilesystemAccessPolicy:
        """Return the contained-Profile native filesystem authority."""
        return cls(
            restricted=True,
            temporary_backing_path=temporary_backing_path.resolve(strict=False),
            read_only_paths=tuple(
                Path(os.path.normpath(str(path))) for path in read_only_paths
            ),
            denied_paths=tuple(
                Path(os.path.normpath(str(path))) for path in denied_paths
            ),
        )


class Workspace:
    """Resolve and authorize operation paths against one Runtime namespace."""

    def __init__(
        self,
        root: str,
        *,
        access_policy: FilesystemAccessPolicy | None = None,
    ) -> None:
        """Initialize the default workspace root and filesystem authority."""
        if not root:
            raise ValueError("workspace root is required")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._access_policy = access_policy or FilesystemAccessPolicy.unrestricted()

    def resolve(self, raw_path: object, *, write: bool = False) -> Path:
        """Resolve a path for a native operation and enforce its authority."""
        logical = self._logical_path(raw_path)
        host = self._host_path(logical, write=write)
        resolved = host.resolve(strict=False)
        self._assert_host_access(resolved, write=write)
        return resolved

    def resolve_lexical(self, raw_path: object, *, write: bool = False) -> Path:
        """Resolve without following the final component while authorizing parents."""
        logical = self._logical_path(raw_path)
        host = self._host_path(logical, write=write)
        self._assert_host_access(host, write=write)
        resolved_parent = host.parent.resolve(strict=False)
        self._assert_host_access(resolved_parent, write=write)
        return host

    def resolve_process_directory(self, raw_path: object) -> Path:
        """Authorize a contained process directory and return its logical path."""
        logical = self._logical_path(raw_path)
        host = self._host_path(logical, write=False).resolve(strict=False)
        self._assert_host_access(host, write=False)
        if not host.is_dir():
            raise ValueError(f"No such directory: {logical}")
        return logical

    def display_path(self, path: Path) -> str:
        """Return the Runtime-visible path for one authorized host path."""
        if not self._access_policy.restricted:
            return str(path.resolve(strict=False))
        return self._display_contained_path(path)

    def display_lexical_path(self, path: Path) -> str:
        """Return a Runtime-visible path without following its final component."""
        if not self._access_policy.restricted:
            return str(path)
        return self._display_contained_path(path)

    def _display_contained_path(self, path: Path) -> str:
        """Map one contained backing path to the Runtime logical namespace."""
        temporary = self._access_policy.temporary_backing_path
        if temporary is not None:
            try:
                relative = path.relative_to(temporary)
            except ValueError:
                pass
            else:
                return str(_LOGICAL_TEMPORARY_ROOT / relative)
        return str(path)

    def resolved_symlink_target(self, path: Path) -> Path | None:
        """Return an authorized symlink target without exposing denied state."""
        resolved = path.resolve(strict=False)
        try:
            self._assert_host_access(resolved, write=False)
        except ValueError:
            return None
        return resolved

    def _logical_path(self, raw_path: object) -> Path:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("path is required")
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.root / path
        return Path(os.path.normpath(str(path)))

    def _host_path(self, logical: Path, *, write: bool) -> Path:
        if not self._access_policy.restricted:
            return logical
        self._assert_not_denied(logical)
        if _path_is_within(logical, self.root):
            return logical
        temporary = self._access_policy.temporary_backing_path
        if temporary is not None and _path_is_within(
            logical,
            _LOGICAL_TEMPORARY_ROOT,
        ):
            relative = logical.relative_to(_LOGICAL_TEMPORARY_ROOT)
            return temporary / relative
        if not write and any(
            _path_is_within(logical, root)
            for root in self._access_policy.read_only_paths
        ):
            return logical
        raise ValueError("path is not permitted by the Runtime Profile")

    def _assert_host_access(self, path: Path, *, write: bool) -> None:
        if not self._access_policy.restricted:
            return
        self._assert_not_denied(path)
        temporary = self._access_policy.temporary_backing_path
        writable_roots = (self.root,) if temporary is None else (self.root, temporary)
        if any(_path_is_within(path, root) for root in writable_roots):
            return
        if not write and any(
            _path_is_within(path, root) for root in self._access_policy.read_only_paths
        ):
            return
        raise ValueError("path is not permitted by the Runtime Profile")

    def _assert_not_denied(self, path: Path) -> None:
        if any(
            _path_is_within(path, denied) for denied in self._access_policy.denied_paths
        ):
            raise ValueError("path is not permitted by the Runtime Profile")


def _path_is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
