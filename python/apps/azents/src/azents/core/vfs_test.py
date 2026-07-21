"""Tests for the run-scoped Azents virtual filesystem domain."""

import base64
import datetime

import pytest

from azents.core.vfs import (
    VFS_FILE_MAX_BYTES,
    VfsProjectionCollisionError,
    VfsSourceSpec,
    VfsUriError,
    canonicalize_vfs_uri,
    make_vfs_file_entry,
    make_vfs_projection,
    make_vfs_source_revision,
)


@pytest.mark.parametrize(
    "uri",
    [
        "azents://skills/azents/deep-research/SKILL.md",
        "azents://skills/github/review-pull-request/templates/review.md",
    ],
)
def test_canonicalize_vfs_uri_accepts_canonical_paths(uri: str) -> None:
    """Canonical VFS URIs retain their exact identity."""
    assert canonicalize_vfs_uri(uri) == uri


@pytest.mark.parametrize(
    "uri",
    [
        "AZENTS://skills/azents/deep-research/SKILL.md",
        "azents://Skills/azents/deep-research/SKILL.md",
        "azents://skills/azents//SKILL.md",
        "azents://skills/azents/../SKILL.md",
        "azents://skills/azents/%2e%2e/SKILL.md",
        "azents://skills/azents/deep-research/SKILL.md?version=1",
        "azents://skills/azents/deep-research/SKILL.md#body",
        "azents://user@skills/azents/deep-research/SKILL.md",
        "azents://skills:443/azents/deep-research/SKILL.md",
        "azents://skills/azents/deep-research\\SKILL.md",
        "/workspace/agent/SKILL.md",
    ],
)
def test_canonicalize_vfs_uri_rejects_ambiguous_paths(uri: str) -> None:
    """Traversal, alternate encoding, and non-canonical forms are rejected."""
    with pytest.raises(VfsUriError):
        canonicalize_vfs_uri(uri)


def test_make_vfs_projection_is_deterministic_and_integrity_checked() -> None:
    """Source ordering does not change the projection hash or file bytes."""
    global_revision = make_vfs_source_revision(
        source_id="release:azents",
        source_kind="global_release",
        namespace="azents",
        entries=[
            (
                "azents://skills/azents/deep-research/SKILL.md",
                b"global",
                "text/markdown",
            )
        ],
    )
    provider_revision = make_vfs_source_revision(
        source_id="toolkit:github",
        source_kind="toolkit_release",
        namespace="github",
        entries=[
            (
                "azents://skills/github/review-pull-request/SKILL.md",
                b"provider",
                "text/markdown",
            )
        ],
    )

    first = make_vfs_projection([provider_revision, global_revision])
    second = make_vfs_projection([global_revision, provider_revision])

    assert first.projection_hash == second.projection_hash
    assert [entry.canonical_uri for entry in first.entries] == sorted(
        entry.canonical_uri for entry in first.entries
    )
    assert first.entries[0].decode_body() == b"global"


def test_make_vfs_projection_rejects_cross_source_collision() -> None:
    """No source precedence hides canonical URI ownership collisions."""
    uri = "azents://skills/azents/deep-research/SKILL.md"
    first = make_vfs_source_revision(
        source_id="source:first",
        source_kind="global_release",
        namespace="azents",
        entries=[(uri, b"one", "text/markdown")],
    )
    second = make_vfs_source_revision(
        source_id="source:second",
        source_kind="global_release",
        namespace="azents",
        entries=[(uri, b"two", "text/markdown")],
    )

    with pytest.raises(VfsProjectionCollisionError):
        make_vfs_projection([first, second])


def test_vfs_file_entry_detects_corrupt_body() -> None:
    """Persisted Base64, size, and content hash are verified on read."""
    entry = make_vfs_file_entry(
        canonical_uri="azents://skills/azents/deep-research/SKILL.md",
        source_id="release:azents",
        source_revision_id="revision",
        body=b"expected",
        media_type="text/markdown",
    )
    corrupt = entry.model_copy(
        update={"body_base64": base64.b64encode(b"changed!").decode("ascii")}
    )

    with pytest.raises(ValueError, match="content hash"):
        corrupt.decode_body()


def test_vfs_file_entry_rejects_oversized_content() -> None:
    """One package resource cannot exceed the VFS per-file cap."""
    with pytest.raises(ValueError, match="exceeds"):
        make_vfs_file_entry(
            canonical_uri="azents://skills/azents/deep-research/SKILL.md",
            source_id="release:azents",
            source_revision_id="revision",
            body=b"x" * (VFS_FILE_MAX_BYTES + 1),
            media_type="text/markdown",
        )


def test_projection_model_round_trip_preserves_created_at() -> None:
    """Projection JSONB serialization round-trips through the domain model."""
    revision = make_vfs_source_revision(
        source_id="release:azents",
        source_kind="global_release",
        namespace="azents",
        entries=[],
    )
    projection = make_vfs_projection([revision])
    restored = type(projection).model_validate(projection.model_dump(mode="json"))

    assert isinstance(restored.created_at, datetime.datetime)
    assert restored == projection


def test_vfs_source_spec_requires_slug_namespace() -> None:
    """Publisher namespaces use stable lowercase URL-safe slugs."""
    with pytest.raises(ValueError):
        VfsSourceSpec(
            source_id="invalid",
            source_kind="global_release",
            namespace="Not Canonical",
            package="azents",
            resource_root="resources/vfs/global",
            required=True,
        )
