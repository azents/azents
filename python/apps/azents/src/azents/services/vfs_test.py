"""Tests for release-backed Azents VFS projection services."""

from azents.core.vfs import VfsSourceSpec
from azents.services.vfs import ReleaseVfsCatalog


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


async def test_release_catalog_reuses_identical_successful_slice() -> None:
    """Repeated source publication retains deterministic revision identity."""
    catalog = ReleaseVfsCatalog()

    first = await catalog.snapshot([_global_spec()])
    second = await catalog.snapshot([_global_spec()])

    assert first.revisions == second.revisions
    assert first.revisions[0].source.source_revision_id == (
        second.revisions[0].source.source_revision_id
    )
