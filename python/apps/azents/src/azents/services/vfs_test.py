"""Tests for release-backed Azents VFS projection services."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from azents.core.vfs import (
    VfsProjection,
    VfsSourceSpec,
    make_vfs_projection,
    make_vfs_source_revision,
)
from azents.repos.toolkit import ToolkitRepository
from azents.services.vfs import (
    ReleaseVfsCatalog,
    VfsFileResolutionError,
    VfsProjectionService,
)


def _global_spec() -> VfsSourceSpec:
    return VfsSourceSpec(
        source_id="release:azents",
        source_kind="global_release",
        namespace="azents",
        package="azents",
        resource_root="resources/vfs/global",
        required=True,
    )


def _github_spec() -> VfsSourceSpec:
    return VfsSourceSpec(
        source_id="toolkit:github",
        source_kind="toolkit_release",
        namespace="github",
        package="azents",
        resource_root="resources/vfs/providers/github",
        required=True,
    )


async def test_release_catalog_loads_global_and_provider_packages() -> None:
    """Packaged global and Provider Skills publish canonical immutable trees."""
    snapshot = await ReleaseVfsCatalog().snapshot([_github_spec(), _global_spec()])

    entries = {
        entry.canonical_uri: entry
        for revision in snapshot.revisions
        for entry in revision.entries
    }
    assert snapshot.diagnostics == []
    assert "azents://skills/azents/deep-research/SKILL.md" in entries
    assert (
        "azents://skills/azents/deep-research/references/evidence-checklist.md"
        in entries
    )
    assert "azents://skills/github/review-pull-request/SKILL.md" in entries
    assert (
        entries["azents://skills/github/review-pull-request/templates/review.md"]
        .decode_body()
        .startswith(b"# Pull Request Review")
    )


def _projection() -> VfsProjection:
    revision = make_vfs_source_revision(
        source_id="release:azents",
        source_kind="global_release",
        namespace="azents",
        entries=[
            (
                "azents://skills/azents/deep-research/SKILL.md",
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


class _AgentToolkitRepository:
    """AgentToolkitRepository test double for Provider eligibility."""

    def __init__(self, attachments: list[object]) -> None:
        self.attachments = attachments

    async def list_by_agent(self, session: object, agent_id: str) -> list[object]:
        """Return the configured Agent Toolkit attachments."""
        del session, agent_id
        return self.attachments


class _ToolkitRepository:
    """ToolkitRepository test double for Provider eligibility."""

    def __init__(self, toolkits: dict[str, object]) -> None:
        self.toolkits = toolkits

    async def get_by_id(self, session: object, toolkit_id: str) -> object | None:
        """Return the configured ToolkitConfig projection."""
        del session
        return self.toolkits.get(toolkit_id)


class _ToolkitSession:
    """AsyncSession test double that returns one raw ToolkitConfig row."""

    def __init__(self, toolkit: object) -> None:
        self.toolkit = toolkit

    async def get(self, model: object, toolkit_id: str) -> object:
        """Return raw metadata with deliberately invalid encrypted credentials."""
        del model, toolkit_id
        return self.toolkit


@asynccontextmanager
async def _session_manager() -> AsyncIterator[object]:
    yield object()


@asynccontextmanager
async def _credential_session_manager() -> AsyncIterator[object]:
    now = datetime.datetime.now(datetime.UTC)
    yield _ToolkitSession(
        SimpleNamespace(
            id="toolkit-1",
            workspace_id="workspace-1",
            toolkit_type="github",
            slug="workspace-github",
            name="GitHub",
            description=None,
            config={},
            prompt=None,
            encrypted_credentials="not-valid-ciphertext",
            enabled=True,
            created_at=now,
            updated_at=now,
        )
    )


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


def _preview_service(*, enabled: bool) -> VfsProjectionService:
    attachment = SimpleNamespace(
        id="attachment-1",
        toolkit_id="toolkit-1",
        toolkit_type="github",
    )
    toolkit = SimpleNamespace(
        enabled=enabled,
        workspace_id="workspace-1",
    )
    provider = SimpleNamespace(
        slug="github",
        vfs_resource_root="resources/vfs/providers/github",
    )
    return VfsProjectionService(
        session_manager=_session_manager,  # pyright: ignore[reportArgumentType]
        toolkit_registry={"github": provider},  # pyright: ignore[reportArgumentType]
        catalog=ReleaseVfsCatalog(),
        agent_run_repository=object(),  # pyright: ignore[reportArgumentType]
        agent_session_repository=object(),  # pyright: ignore[reportArgumentType]
        agent_toolkit_repository=_AgentToolkitRepository(  # pyright: ignore[reportArgumentType]
            [attachment]
        ),
        toolkit_repository=_ToolkitRepository(  # pyright: ignore[reportArgumentType]
            {"toolkit-1": toolkit}
        ),
    )


async def test_release_catalog_reuses_identical_successful_slice() -> None:
    """Repeated source publication retains deterministic revision identity."""
    catalog = ReleaseVfsCatalog()

    first = await catalog.snapshot([_global_spec()])
    second = await catalog.snapshot([_global_spec()])

    assert first.revisions == second.revisions
    assert first.revisions[0].source.source_revision_id == (
        second.revisions[0].source.source_revision_id
    )


@pytest.mark.parametrize(
    ("enabled", "provider_expected"), [(True, True), (False, False)]
)
async def test_preview_filters_provider_source_by_enabled_toolkit(
    enabled: bool,
    provider_expected: bool,
) -> None:
    """Provider packages require an enabled attached ToolkitConfig."""
    projection = await _preview_service(enabled=enabled).build_preview(
        agent_id="agent-1",
        workspace_id="workspace-1",
    )

    assert (
        projection.find("azents://skills/github/review-pull-request/SKILL.md")
        is not None
    ) is provider_expected
    assert projection.find("azents://skills/azents/deep-research/SKILL.md") is not None


async def test_preview_eligibility_does_not_decrypt_toolkit_credentials() -> None:
    """Corrupt encrypted credentials do not affect release source eligibility."""
    attachment = SimpleNamespace(
        id="attachment-1",
        toolkit_id="toolkit-1",
        toolkit_type="github",
    )
    provider = SimpleNamespace(
        slug="github",
        vfs_resource_root="resources/vfs/providers/github",
    )
    service = VfsProjectionService(
        session_manager=_credential_session_manager,  # pyright: ignore[reportArgumentType]
        toolkit_registry={"github": provider},  # pyright: ignore[reportArgumentType]
        catalog=ReleaseVfsCatalog(),
        agent_run_repository=object(),  # pyright: ignore[reportArgumentType]
        agent_session_repository=object(),  # pyright: ignore[reportArgumentType]
        agent_toolkit_repository=_AgentToolkitRepository(  # pyright: ignore[reportArgumentType]
            [attachment]
        ),
        toolkit_repository=ToolkitRepository(),
    )

    projection = await service.build_preview(
        agent_id="agent-1",
        workspace_id="workspace-1",
    )

    assert projection.find("azents://skills/github/review-pull-request/SKILL.md")


async def test_resolve_file_returns_projection_provenance_and_verified_entry() -> None:
    """Authorized lookup returns immutable projection and source identity."""
    projection = _projection()
    uri = "azents://skills/azents/deep-research/SKILL.md"

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
            uri="azents://skills/azents/deep-research/SKILL.md",
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
                "azents://skills/azents/deep-research/SKILL.md",
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
