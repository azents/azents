"""Tests for release-backed Azents VFS projection services."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from azents.core.vfs import (
    VfsProjection,
    make_vfs_projection,
    make_vfs_source_revision,
)
from azents.services.vfs import (
    ReleaseVfsCatalog,
    VfsFileResolutionError,
    VfsProjectionService,
)


async def test_release_catalog_allows_an_empty_catalog() -> None:
    """No approved release resources produce a valid empty catalog."""
    snapshot = await ReleaseVfsCatalog().snapshot([])

    assert snapshot.diagnostics == []
    assert snapshot.revisions == []


def _projection() -> VfsProjection:
    revision = make_vfs_source_revision(
        source_id="release:azents",
        source_kind="global_release",
        namespace="azents",
        entries=[
            (
                "azents://skills/test/sample/SKILL.md",
                b"---\ndescription: Research deeply.\n---\nBody",
                "text/markdown",
            )
        ],
    )
    return make_vfs_projection([revision])


class _RunRepository:
    """AgentRunRepository test double."""

    def __init__(self, projection: VfsProjection) -> None:
        self.projection = projection

    async def get_by_id(self, session: object, run_id: str) -> object:
        del session, run_id
        return SimpleNamespace(session_id="session-1", vfs_projection=self.projection)


class _SessionRepository:
    """AgentSessionRepository test double."""

    async def get_by_id(self, session: object, session_id: str) -> object:
        del session, session_id
        return SimpleNamespace(agent_id="agent-1", workspace_id="workspace-1")


class _MappedRunRepository:
    """AgentRunRepository test double with per-run projections."""

    def __init__(self, runs: dict[str, object]) -> None:
        self.runs = runs

    async def get_by_id(self, session: object, run_id: str) -> object | None:
        """Return the configured run without falling back to another run."""
        del session
        return self.runs.get(run_id)


class _MappedSessionRepository:
    """AgentSessionRepository test double with per-session ownership."""

    def __init__(self, sessions: dict[str, object]) -> None:
        self.sessions = sessions

    async def get_by_id(self, session: object, session_id: str) -> object | None:
        """Return the configured Session ownership record."""
        del session
        return self.sessions.get(session_id)


@asynccontextmanager
async def _session_manager() -> AsyncIterator[object]:
    yield object()


def _projection_service(projection: VfsProjection) -> VfsProjectionService:
    return VfsProjectionService(
        session_manager=_session_manager,  # pyright: ignore[reportArgumentType]
        toolkit_registry={},
        catalog=ReleaseVfsCatalog(),
        agent_run_repository=_RunRepository(projection),  # pyright: ignore[reportArgumentType]
        agent_session_repository=_SessionRepository(),  # pyright: ignore[reportArgumentType]
        agent_toolkit_repository=object(),  # pyright: ignore[reportArgumentType]
        toolkit_repository=object(),  # pyright: ignore[reportArgumentType]
    )


async def test_release_catalog_reuses_an_empty_catalog() -> None:
    """Repeated empty catalog publication is stable."""
    catalog = ReleaseVfsCatalog()

    first = await catalog.snapshot([])
    second = await catalog.snapshot([])

    assert first.revisions == second.revisions
    assert first.diagnostics == second.diagnostics == []


async def test_resolve_file_returns_projection_provenance_and_verified_entry() -> None:
    """Authorized lookup returns immutable projection and source identity."""
    projection = _projection()
    uri = "azents://skills/test/sample/SKILL.md"

    resolved = await _projection_service(projection).resolve_file(
        run_id="run-1",
        agent_id="agent-1",
        session_id="session-1",
        workspace_id="workspace-1",
        uri=uri,
    )

    assert resolved.projection_revision_id == projection.revision_id
    assert resolved.projection_hash == projection.projection_hash
    assert resolved.entry.canonical_uri == uri
    assert resolved.entry.decode_body().endswith(b"Body")


async def test_resolve_file_rejects_noncanonical_uri_before_lookup() -> None:
    """Canonical URI validation runs before projection membership lookup."""
    service = _projection_service(_projection())

    with pytest.raises(VfsFileResolutionError) as exc_info:
        await service.resolve_file(
            run_id="run-1",
            agent_id="agent-1",
            session_id="session-1",
            workspace_id="workspace-1",
            uri="azents://skills/azents/../secret",
        )

    assert exc_info.value.code == "invalid_uri"


async def test_resolve_file_rejects_unsupported_mount() -> None:
    """A canonical URI under an unregistered mount has a distinct failure code."""
    service = _projection_service(_projection())

    with pytest.raises(VfsFileResolutionError) as exc_info:
        await service.resolve_file(
            run_id="run-1",
            agent_id="agent-1",
            session_id="session-1",
            workspace_id="workspace-1",
            uri="azents://templates/azents/review.md",
        )

    assert exc_info.value.code == "unsupported_mount"


async def test_resolve_file_rejects_workspace_ownership_mismatch() -> None:
    """A URI and run ID do not bypass AgentSession ownership checks."""
    service = _projection_service(_projection())

    with pytest.raises(VfsFileResolutionError) as exc_info:
        await service.resolve_file(
            run_id="run-1",
            agent_id="agent-1",
            session_id="session-1",
            workspace_id="other-workspace",
            uri="azents://skills/test/sample/SKILL.md",
        )

    assert exc_info.value.code == "permission_denied"


async def test_subagent_run_loads_its_own_projection() -> None:
    """A child run resolves its row projection instead of inheriting its parent."""
    parent_projection = _projection()
    child_revision = make_vfs_source_revision(
        source_id="release:azents",
        source_kind="global_release",
        namespace="azents",
        entries=[
            (
                "azents://skills/test/sample/SKILL.md",
                b"---\ndescription: Child projection.\n---\nChild body",
                "text/markdown",
            )
        ],
    )
    child_projection = make_vfs_projection([child_revision])
    service = VfsProjectionService(
        session_manager=_session_manager,  # pyright: ignore[reportArgumentType]
        toolkit_registry={},
        catalog=ReleaseVfsCatalog(),
        agent_run_repository=_MappedRunRepository(  # pyright: ignore[reportArgumentType]
            {
                "parent-run": SimpleNamespace(
                    session_id="parent-session",
                    vfs_projection=parent_projection,
                ),
                "child-run": SimpleNamespace(
                    session_id="child-session",
                    vfs_projection=child_projection,
                ),
            }
        ),
        agent_session_repository=_MappedSessionRepository(  # pyright: ignore[reportArgumentType]
            {
                "parent-session": SimpleNamespace(
                    agent_id="parent-agent",
                    workspace_id="workspace-1",
                ),
                "child-session": SimpleNamespace(
                    agent_id="child-agent",
                    workspace_id="workspace-1",
                ),
            }
        ),
        agent_toolkit_repository=object(),  # pyright: ignore[reportArgumentType]
        toolkit_repository=object(),  # pyright: ignore[reportArgumentType]
    )

    loaded = await service.load_run_projection(
        run_id="child-run",
        agent_id="child-agent",
        session_id="child-session",
        workspace_id="workspace-1",
    )

    assert loaded == child_projection
    assert loaded != parent_projection
