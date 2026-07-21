"""Run-scoped Azents virtual filesystem projection service."""

import asyncio
import dataclasses
import logging
import mimetypes
import pathlib
import posixpath
import time
from collections.abc import Mapping, Sequence
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.tools import ToolkitProvider
from azents.core.vfs import (
    AZENTS_VFS_SUPPORTED_MOUNTS,
    VfsFileEntry,
    VfsProjection,
    VfsSourceRevision,
    VfsSourceSpec,
    VfsUriError,
    canonicalize_vfs_uri,
    make_vfs_projection,
    make_vfs_source_revision,
    make_vfs_uri,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository

logger = logging.getLogger(__name__)


class VfsFileResolutionError(Exception):
    """Authorized run VFS file resolution failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclasses.dataclass(frozen=True)
class VfsCatalogSnapshot:
    """Published release source revisions and bounded diagnostics."""

    revisions: list[VfsSourceRevision]
    diagnostics: list[str]


@dataclasses.dataclass(frozen=True)
class VfsResolvedFile:
    """One verified file and the persisted projection that authorized it."""

    projection_revision_id: str
    projection_hash: str
    entry: VfsFileEntry


class ReleaseVfsCatalog:
    """Load package resources while retaining independent successful slices."""

    def __init__(self) -> None:
        """Create an empty release source cache."""
        self._lock = asyncio.Lock()
        self._successful: dict[str, VfsSourceRevision] = {}

    async def snapshot(
        self,
        specs: Sequence[VfsSourceSpec],
    ) -> VfsCatalogSnapshot:
        """Publish current package revisions and retain prior successful slices."""
        revisions: list[VfsSourceRevision] = []
        diagnostics: list[str] = []
        async with self._lock:
            for spec in sorted(specs, key=lambda candidate: candidate.source_id):
                try:
                    revision = _load_release_source(spec)
                except (OSError, ValueError) as exc:
                    previous = self._successful.get(spec.source_id)
                    if previous is not None:
                        revisions.append(previous)
                        diagnostics.append(
                            f"Retained last successful VFS source {spec.source_id}: "
                            f"{type(exc).__name__}"
                        )
                        continue
                    if spec.required:
                        raise
                    diagnostics.append(
                        f"Skipped unavailable VFS source {spec.source_id}: "
                        f"{type(exc).__name__}"
                    )
                    continue
                self._successful[spec.source_id] = revision
                revisions.append(revision)
        return VfsCatalogSnapshot(revisions=revisions, diagnostics=diagnostics)


@dataclasses.dataclass(frozen=True)
class VfsProjectionService:
    """Build and persist immutable VFS projections for Agent runs."""

    session_manager: SessionManager[AsyncSession]
    toolkit_registry: Mapping[str, ToolkitProvider[Any]]
    catalog: ReleaseVfsCatalog
    agent_run_repository: AgentRunRepository
    agent_session_repository: AgentSessionRepository
    agent_toolkit_repository: AgentToolkitRepository
    toolkit_repository: ToolkitRepository

    async def build_preview(
        self,
        *,
        agent_id: str,
        workspace_id: str,
    ) -> VfsProjection:
        """Build a non-persisted projection from current eligible release sources."""
        started_at = time.monotonic()
        provider_specs = await self._eligible_provider_specs(
            agent_id=agent_id,
            workspace_id=workspace_id,
        )
        catalog_snapshot = await self.catalog.snapshot(provider_specs)
        projection = make_vfs_projection(
            catalog_snapshot.revisions,
            diagnostics=catalog_snapshot.diagnostics,
        )
        logger.info(
            "VFS projection built",
            extra={
                "agent_id": agent_id,
                "workspace_id": workspace_id,
                "projection_hash": projection.projection_hash,
                "source_count": len(projection.sources),
                "entry_count": len(projection.entries),
                "size_bytes": sum(entry.size_bytes for entry in projection.entries),
                "diagnostic_count": len(projection.diagnostics),
                "duration_seconds": round(time.monotonic() - started_at, 3),
            },
        )
        return projection

    async def ensure_run_projection(
        self,
        *,
        run_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
    ) -> VfsProjection:
        """Return the run's immutable projection, creating it exactly once."""
        async with self.session_manager() as session:
            run = await self.agent_run_repository.get_by_id(session, run_id)
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
        if run is None or run.session_id != session_id or agent_session is None:
            raise ValueError("AgentRun not found in session")
        if (
            agent_session.agent_id != agent_id
            or agent_session.workspace_id != workspace_id
        ):
            raise ValueError("AgentRun ownership mismatch")
        if run.vfs_projection is not None:
            return run.vfs_projection

        candidate = await self.build_preview(
            agent_id=agent_id,
            workspace_id=workspace_id,
        )
        async with self.session_manager() as session:
            projection = await self.agent_run_repository.set_vfs_projection_if_unset(
                session,
                run_id=run_id,
                session_id=session_id,
                projection=candidate,
            )
            await session.commit()
        return projection

    async def load_run_projection(
        self,
        *,
        run_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
    ) -> VfsProjection:
        """Load one run projection after validating its complete ownership chain."""
        async with self.session_manager() as session:
            run = await self.agent_run_repository.get_by_id(session, run_id)
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
        if run is None or run.session_id != session_id or agent_session is None:
            raise VfsFileResolutionError("not_found", "Run VFS projection not found")
        if (
            agent_session.agent_id != agent_id
            or agent_session.workspace_id != workspace_id
        ):
            raise VfsFileResolutionError(
                "permission_denied",
                "Run VFS projection access denied",
            )
        if run.vfs_projection is None:
            raise VfsFileResolutionError(
                "storage_unavailable",
                "Run VFS projection is unavailable",
            )
        return run.vfs_projection

    async def projection_for_actions(
        self,
        *,
        agent_id: str,
        session_id: str,
        workspace_id: str,
        running: bool,
        active_run_id: str | None,
    ) -> VfsProjection:
        """Return the exact active run projection or an idle composer preview."""
        if running:
            if active_run_id is None:
                raise VfsFileResolutionError(
                    "storage_unavailable",
                    "Active run VFS projection is unavailable",
                )
            return await self.load_run_projection(
                run_id=active_run_id,
                agent_id=agent_id,
                session_id=session_id,
                workspace_id=workspace_id,
            )
        return await self.build_preview(
            agent_id=agent_id,
            workspace_id=workspace_id,
        )

    async def resolve_file(
        self,
        *,
        run_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
        uri: str,
    ) -> VfsResolvedFile:
        """Resolve one exact authorized file from a persisted run projection."""
        try:
            canonical_uri = canonicalize_vfs_uri(uri)
        except VfsUriError as exc:
            raise VfsFileResolutionError("invalid_uri", str(exc)) from exc
        mount = canonical_uri.split("://", 1)[1].split("/", 1)[0]
        if mount not in AZENTS_VFS_SUPPORTED_MOUNTS:
            raise VfsFileResolutionError(
                "unsupported_mount",
                f"Unsupported azents:// mount: {mount}",
            )
        projection = await self.load_run_projection(
            run_id=run_id,
            agent_id=agent_id,
            session_id=session_id,
            workspace_id=workspace_id,
        )
        entry = projection.find(canonical_uri)
        if entry is None:
            raise VfsFileResolutionError(
                "not_found",
                f"VFS file not found in the current run projection: {canonical_uri}",
            )
        try:
            entry.decode_body()
        except ValueError as exc:
            raise VfsFileResolutionError(
                "storage_unavailable",
                f"VFS file content is unavailable: {canonical_uri}",
            ) from exc
        return VfsResolvedFile(
            projection_revision_id=projection.revision_id,
            projection_hash=projection.projection_hash,
            entry=entry,
        )

    async def _eligible_provider_specs(
        self,
        *,
        agent_id: str,
        workspace_id: str,
    ) -> list[VfsSourceSpec]:
        """Return enabled Provider release sources eligible for one Agent."""
        async with self.session_manager() as session:
            attachments = await self.agent_toolkit_repository.list_by_agent(
                session,
                agent_id,
            )
            toolkit_configs = {
                attachment.id: await self.toolkit_repository.get_by_id(
                    session,
                    attachment.toolkit_id,
                )
                for attachment in attachments
            }
        eligible_providers: dict[str, ToolkitProvider[Any]] = {}
        for attachment in attachments:
            toolkit = toolkit_configs[attachment.id]
            if (
                toolkit is None
                or not toolkit.enabled
                or toolkit.workspace_id != workspace_id
            ):
                continue
            provider = self.toolkit_registry.get(attachment.toolkit_type)
            if provider is None or provider.vfs_resource_root is None:
                continue
            eligible_providers[provider.slug] = provider

        specs: list[VfsSourceSpec] = []
        for slug, provider in sorted(eligible_providers.items()):
            resource_root = provider.vfs_resource_root
            if resource_root is None:
                continue
            specs.append(
                VfsSourceSpec(
                    source_id=f"toolkit:{slug}",
                    source_kind="toolkit_release",
                    namespace=slug,
                    package="azents",
                    resource_root=resource_root,
                    required=True,
                )
            )
        return specs


def _load_release_source(spec: VfsSourceSpec) -> VfsSourceRevision:
    """Read and publish one package-resource VFS source."""
    root = resources.files(spec.package).joinpath(spec.resource_root)
    if not root.is_dir():
        raise ValueError(f"VFS source root is not a directory: {spec.source_id}")
    files: list[tuple[str, bytes, str]] = []
    for relative_path, item in _walk_resource_files(root):
        mount, separator, mount_relative = relative_path.partition("/")
        if not separator or not mount_relative:
            raise ValueError(
                f"VFS source file must be below a mount directory: {relative_path}"
            )
        if mount not in AZENTS_VFS_SUPPORTED_MOUNTS:
            raise ValueError(f"Unsupported VFS source mount: {mount}")
        canonical_uri = make_vfs_uri(mount, spec.namespace, mount_relative)
        body = item.read_bytes()
        media_type = mimetypes.guess_type(posixpath.basename(relative_path))[0]
        files.append((canonical_uri, body, media_type or "application/octet-stream"))
    return make_vfs_source_revision(
        source_id=spec.source_id,
        source_kind=spec.source_kind,
        namespace=spec.namespace,
        entries=files,
    )


def _walk_resource_files(root: Traversable) -> list[tuple[str, Traversable]]:
    """Return deterministic package files below a source root."""
    files: list[tuple[str, Traversable]] = []

    def visit(directory: Traversable, prefix: str) -> None:
        for item in sorted(directory.iterdir(), key=lambda candidate: candidate.name):
            relative_path = posixpath.join(prefix, item.name) if prefix else item.name
            if item.name in {".", ".."} or "/" in item.name or "\\" in item.name:
                raise ValueError(f"Invalid VFS package resource name: {item.name}")
            if isinstance(item, pathlib.Path) and item.is_symlink():
                raise ValueError(f"VFS package resources must not be symlinks: {item}")
            if item.is_dir():
                visit(item, relative_path)
            elif item.is_file():
                files.append((relative_path, item))
            else:
                raise ValueError(f"Unsupported VFS package resource: {relative_path}")

    visit(root, "")
    return files
