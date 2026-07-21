"""Run-scoped read-only Azents virtual filesystem models."""

import base64
import binascii
import datetime
import hashlib
import json
import re
from collections.abc import Iterable
from typing import Literal
from urllib.parse import urlsplit

from azcommon.uuid import uuid7
from pydantic import BaseModel, ConfigDict, Field

VFS_SCHEMA_VERSION = 1
AZENTS_VFS_SCHEME = "azents"
AZENTS_VFS_SKILLS_MOUNT = "skills"
AZENTS_VFS_SUPPORTED_MOUNTS = frozenset({AZENTS_VFS_SKILLS_MOUNT})
VFS_FILE_MAX_BYTES = 2 * 1024 * 1024
VFS_PROJECTION_MAX_BYTES = 8 * 1024 * 1024

VfsSourceKind = Literal["global_release", "toolkit_release"]

_MOUNT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_PATH_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


class VfsUriError(ValueError):
    """Invalid or non-canonical Azents VFS URI."""


class VfsProjectionCollisionError(ValueError):
    """Multiple VFS sources published the same canonical URI."""


class VfsSourceRef(BaseModel):
    """Immutable source revision selected into a VFS projection."""

    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1)
    source_kind: VfsSourceKind
    namespace: str = Field(min_length=1)
    source_revision_id: str = Field(min_length=1)
    source_hash: str = Field(min_length=64, max_length=64)


class VfsFileEntry(BaseModel):
    """One immutable file included in a run VFS projection."""

    model_config = ConfigDict(frozen=True)

    canonical_uri: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_revision_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0, le=VFS_FILE_MAX_BYTES)
    media_type: str = Field(min_length=1)
    body_base64: str

    def decode_body(self) -> bytes:
        """Decode and verify the immutable file body."""
        try:
            body = base64.b64decode(self.body_base64, validate=True)
        except binascii.Error as exc:
            raise ValueError("VFS file body is not valid Base64") from exc
        if len(body) != self.size_bytes:
            raise ValueError("VFS file size does not match the manifest")
        if hashlib.sha256(body).hexdigest() != self.content_hash:
            raise ValueError("VFS file content hash does not match the manifest")
        return body


class VfsSourceRevision(BaseModel):
    """One immutable file-tree revision published by a VFS source."""

    model_config = ConfigDict(frozen=True)

    source: VfsSourceRef
    entries: list[VfsFileEntry] = Field(default_factory=list)


class VfsProjection(BaseModel):
    """Complete immutable Azents VFS view authorized for one run."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = VFS_SCHEMA_VERSION
    revision_id: str = Field(default_factory=lambda: uuid7().hex)
    projection_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime.datetime
    sources: list[VfsSourceRef] = Field(default_factory=list)
    entries: list[VfsFileEntry] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)

    def find(self, uri: str) -> VfsFileEntry | None:
        """Resolve an exact canonical URI from this projection."""
        canonical = canonicalize_vfs_uri(uri)
        return next(
            (entry for entry in self.entries if entry.canonical_uri == canonical),
            None,
        )


class VfsSourceSpec(BaseModel):
    """Python package resource source registered for release publication."""

    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1)
    source_kind: VfsSourceKind
    namespace: str = Field(pattern=_SLUG_PATTERN.pattern)
    package: str = Field(min_length=1)
    resource_root: str = Field(min_length=1)
    required: bool


def canonicalize_vfs_uri(uri: str) -> str:
    """Validate and return the canonical Azents VFS URI string."""
    if not uri or "%" in uri or "\\" in uri:
        raise VfsUriError("Invalid azents:// URI")
    parsed = urlsplit(uri)
    if parsed.scheme != AZENTS_VFS_SCHEME:
        raise VfsUriError("Invalid azents:// URI scheme")
    if parsed.username is not None or parsed.password is not None:
        raise VfsUriError("azents:// URI must not contain user information")
    try:
        port = parsed.port
    except ValueError as exc:
        raise VfsUriError("azents:// URI has an invalid port") from exc
    if port is not None or parsed.query or parsed.fragment:
        raise VfsUriError("azents:// URI must not contain port, query, or fragment")
    mount = parsed.hostname
    if mount is None or parsed.netloc != mount or not _MOUNT_PATTERN.fullmatch(mount):
        raise VfsUriError("azents:// URI has an invalid mount")
    if not parsed.path.startswith("/"):
        raise VfsUriError("azents:// URI path must be absolute")
    segments = parsed.path.split("/")[1:]
    if not segments or any(
        not segment
        or segment in {".", ".."}
        or not _PATH_SEGMENT_PATTERN.fullmatch(segment)
        for segment in segments
    ):
        raise VfsUriError("azents:// URI has an invalid path")
    canonical = f"{AZENTS_VFS_SCHEME}://{mount}/{'/'.join(segments)}"
    if canonical != uri:
        raise VfsUriError("azents:// URI is not canonical")
    return canonical


def make_vfs_uri(mount: str, namespace: str, relative_path: str) -> str:
    """Build and validate a canonical VFS URI from source-owned segments."""
    normalized_relative = relative_path.strip("/")
    return canonicalize_vfs_uri(
        f"{AZENTS_VFS_SCHEME}://{mount}/{namespace}/{normalized_relative}"
    )


def make_vfs_file_entry(
    *,
    canonical_uri: str,
    source_id: str,
    source_revision_id: str,
    body: bytes,
    media_type: str,
) -> VfsFileEntry:
    """Create one content-verified immutable VFS entry."""
    canonical = canonicalize_vfs_uri(canonical_uri)
    if len(body) > VFS_FILE_MAX_BYTES:
        raise ValueError(f"VFS file exceeds {VFS_FILE_MAX_BYTES} bytes: {canonical}")
    return VfsFileEntry(
        canonical_uri=canonical,
        source_id=source_id,
        source_revision_id=source_revision_id,
        content_hash=hashlib.sha256(body).hexdigest(),
        size_bytes=len(body),
        media_type=media_type,
        body_base64=base64.b64encode(body).decode("ascii"),
    )


def make_vfs_source_revision(
    *,
    source_id: str,
    source_kind: VfsSourceKind,
    namespace: str,
    entries: Iterable[tuple[str, bytes, str]],
) -> VfsSourceRevision:
    """Create a deterministic immutable source revision."""
    provisional = sorted(entries, key=lambda item: item[0])
    source_payload = [
        {
            "canonical_uri": canonicalize_vfs_uri(uri),
            "content_hash": hashlib.sha256(body).hexdigest(),
            "media_type": media_type,
            "size_bytes": len(body),
        }
        for uri, body, media_type in provisional
    ]
    source_hash = hashlib.sha256(
        json.dumps(source_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    source_revision_id = source_hash
    files = [
        make_vfs_file_entry(
            canonical_uri=uri,
            source_id=source_id,
            source_revision_id=source_revision_id,
            body=body,
            media_type=media_type,
        )
        for uri, body, media_type in provisional
    ]
    return VfsSourceRevision(
        source=VfsSourceRef(
            source_id=source_id,
            source_kind=source_kind,
            namespace=namespace,
            source_revision_id=source_revision_id,
            source_hash=source_hash,
        ),
        entries=files,
    )


def make_vfs_projection(
    revisions: Iterable[VfsSourceRevision],
    *,
    diagnostics: Iterable[str] = (),
) -> VfsProjection:
    """Merge source revisions into one deterministic immutable projection."""
    ordered_revisions = sorted(
        revisions,
        key=lambda revision: (
            revision.source.source_kind,
            revision.source.namespace,
            revision.source.source_id,
        ),
    )
    entries_by_uri: dict[str, VfsFileEntry] = {}
    total_bytes = 0
    for revision in ordered_revisions:
        for entry in sorted(
            revision.entries, key=lambda candidate: candidate.canonical_uri
        ):
            existing = entries_by_uri.get(entry.canonical_uri)
            if existing is not None:
                raise VfsProjectionCollisionError(
                    "VFS URI collision between "
                    f"{existing.source_id} and {entry.source_id}: "
                    f"{entry.canonical_uri}"
                )
            entries_by_uri[entry.canonical_uri] = entry
            total_bytes += entry.size_bytes
    if total_bytes > VFS_PROJECTION_MAX_BYTES:
        raise ValueError(
            f"VFS projection exceeds {VFS_PROJECTION_MAX_BYTES} decoded bytes"
        )
    ordered_entries = [entries_by_uri[uri] for uri in sorted(entries_by_uri)]
    projection_payload = {
        "sources": [
            source.source.model_dump(mode="json") for source in ordered_revisions
        ],
        "entries": [
            {
                "canonical_uri": entry.canonical_uri,
                "source_id": entry.source_id,
                "source_revision_id": entry.source_revision_id,
                "content_hash": entry.content_hash,
                "size_bytes": entry.size_bytes,
                "media_type": entry.media_type,
            }
            for entry in ordered_entries
        ],
    }
    projection_hash = hashlib.sha256(
        json.dumps(projection_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return VfsProjection(
        projection_hash=projection_hash,
        created_at=datetime.datetime.now(datetime.UTC),
        sources=[revision.source for revision in ordered_revisions],
        entries=ordered_entries,
        diagnostics=sorted(set(diagnostics)),
    )
