"""Google file bridge uses existing canonical resolvers and bounded product storage."""

import dataclasses
import datetime
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, NonCallableMock, create_autospec

import pytest
from azcommon.infra.s3.service import S3ObjectIdentity, S3Service
from azcommon.result import Failure, Success

from azents.core.enums import ArtifactStatus
from azents.core.google_oauth import GoogleOAuthError
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.core.vfs import make_vfs_file_entry
from azents.engine.tools.google_files import GoogleFileBridge
from azents.engine.tools.import_resolver import (
    ImportFileResolverRegistry,
    ResolvedArtifactImportSource,
    ResolvedVfsImportSource,
)
from azents.repos.artifact.data import Artifact
from azents.services.artifact import (
    ArtifactAccessDenied,
    ArtifactService,
    ArtifactTransferSource,
)
from azents.services.google_workspace.errors import GoogleWorkspacePartialError
from azents.services.google_workspace.file_models import (
    GoogleFileInput,
    GooglePreparedFile,
)
from azents.services.google_workspace.transport import GoogleSdkError
from azents.services.vfs import VfsResolvedFile


def _mock(value: object) -> NonCallableMock:
    assert isinstance(value, NonCallableMock)
    return value


def _authority() -> SessionResourceAuthority:
    return SessionResourceAuthority(
        "workspace", "agent", "session", "session", "run", 1, 7
    )


def _artifact(content: bytes) -> Artifact:
    now = datetime.datetime.now(datetime.UTC)
    return Artifact(
        id="artifact",
        workspace_id="workspace",
        agent_id="agent",
        session_id="session",
        created_run_id="run",
        created_run_index=1,
        expires_at=now + datetime.timedelta(hours=1),
        name="source.txt",
        media_type="text/plain",
        size_bytes=len(content),
        storage_key="canonical-object",
        status=ArtifactStatus.AVAILABLE,
        sha256=hashlib.sha256(content).hexdigest(),
        created_at=now,
    )


def _bridge() -> GoogleFileBridge:
    return GoogleFileBridge(
        resolver=create_autospec(ImportFileResolverRegistry, instance=True),
        runtime=None,
        s3=create_autospec(S3Service, instance=True),
        bucket="fixture-bucket",
        artifacts=create_autospec(ArtifactService, instance=True),
        authority=_authority(),
        maximum_bytes=1024,
    )


def _vfs(content: bytes, revalidate: AsyncMock) -> ResolvedVfsImportSource:
    entry = make_vfs_file_entry(
        canonical_uri="azents://execution/output.txt",
        source_id="execution",
        source_revision_id="revision",
        body=content,
        media_type="text/plain",
    )
    return ResolvedVfsImportSource(
        source=VfsResolvedFile("projection", "projection-hash", entry),
        name="output.txt",
        media_type="text/plain",
        size=len(content),
        source_uri=entry.canonical_uri,
        source_kind="azents",
        revalidate=revalidate,
    )


async def test_vfs_source_is_verified_revalidated_without_runtime_or_object_io() -> (
    None
):
    bridge = _bridge()
    check = AsyncMock(return_value=True)
    resolved = _vfs(b"verified body", check)
    resolver = bridge.resolver.resolve
    assert isinstance(resolver, AsyncMock)
    resolver.return_value = resolved
    admit = AsyncMock()
    result = await bridge.resolve(
        GoogleFileInput(source=resolved.source_uri, filename=None, media_type=None),
        admit=admit,
    )
    assert result.file.content == b"verified body"
    assert result.file.sha256 == resolved.source.entry.content_hash
    assert check.await_count == 2
    await result.revalidate()
    assert check.await_count == 3
    _mock(bridge.s3).iter_chunks.assert_not_called()
    admit.assert_awaited()


async def test_vfs_revision_change_after_materialization_blocks_provider_reuse() -> (
    None
):
    bridge = _bridge()
    check = AsyncMock(side_effect=[True, True, False])
    source = _vfs(b"body", check)
    _mock(bridge.resolver).resolve.return_value = source
    result = await bridge.resolve(
        GoogleFileInput(source=source.source_uri, filename=None, media_type=None),
        admit=AsyncMock(),
    )
    with pytest.raises(GoogleSdkError) as error:
        await result.revalidate()
    assert error.value.code == "file_source_changed"


async def test_stale_source_is_rejected_before_any_body_read() -> None:
    bridge = _bridge()
    source = _vfs(b"body", AsyncMock(return_value=False))
    _mock(bridge.resolver).resolve.return_value = source
    with pytest.raises(GoogleSdkError) as error:
        await bridge.resolve(
            GoogleFileInput(source=source.source_uri, filename=None, media_type=None),
            admit=AsyncMock(),
        )
    assert error.value.code == "file_source_changed"
    _mock(bridge.s3).iter_chunks.assert_not_called()


async def test_s3_source_is_streamed_to_exact_authorized_size_and_hash() -> None:
    bridge = _bridge()
    content = b"verified source bytes"
    artifact = _artifact(content)
    source = ResolvedArtifactImportSource(
        source=ArtifactTransferSource(artifact),
        name=artifact.name,
        media_type=artifact.media_type,
        size=artifact.size_bytes,
        source_uri=artifact.uri,
        source_kind="artifact",
        revalidate=AsyncMock(return_value=True),
    )
    _mock(bridge.resolver).resolve.return_value = source
    identities: list[S3ObjectIdentity] = []
    closed = False

    @asynccontextmanager
    async def stream(
        identity: S3ObjectIdentity, *, maximum_chunk_size: int
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        nonlocal closed
        identities.append(identity)

        async def chunks() -> AsyncIterator[bytes]:
            yield content[:4]
            yield content[4:]

        try:
            yield chunks()
        finally:
            closed = True

    _mock(bridge.s3).iter_chunks.side_effect = stream
    result = await bridge.resolve(
        GoogleFileInput(source=artifact.uri, filename=None, media_type=None),
        admit=AsyncMock(),
    )
    assert result.file.content == content and closed
    assert identities == [
        S3ObjectIdentity(bucket="fixture-bucket", key="canonical-object")
    ]


@pytest.mark.parametrize("body", [b"bad", b"longer than known"])
async def test_wrong_object_body_never_reaches_sdk_input(body: bytes) -> None:
    bridge = _bridge()
    artifact = _artifact(b"known")
    _mock(bridge.resolver).resolve.return_value = ResolvedArtifactImportSource(
        source=ArtifactTransferSource(artifact),
        name=artifact.name,
        media_type=artifact.media_type,
        size=artifact.size_bytes,
        source_uri=artifact.uri,
        source_kind="artifact",
        revalidate=AsyncMock(return_value=True),
    )

    @asynccontextmanager
    async def stream(
        identity: S3ObjectIdentity, *, maximum_chunk_size: int
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        async def chunks() -> AsyncIterator[bytes]:
            yield body

        yield chunks()

    _mock(bridge.s3).iter_chunks.side_effect = stream
    with pytest.raises(GoogleSdkError) as error:
        await bridge.resolve(
            GoogleFileInput(source=artifact.uri, filename=None, media_type=None),
            admit=AsyncMock(),
        )
    assert error.value.code == "file_integrity_mismatch"


@pytest.mark.parametrize(
    "source", ["relative.txt", "/workspace/file.txt", "C:\\runtime\\file.txt"]
)
async def test_runtime_paths_never_fall_back_to_backend_filesystem(source: str) -> None:
    bridge = _bridge()
    with pytest.raises(GoogleSdkError) as error:
        await bridge.resolve(
            GoogleFileInput(source=source, filename=None, media_type=None),
            admit=AsyncMock(),
        )
    assert error.value.code == "runtime_source_unavailable"
    _mock(bridge.resolver).resolve.assert_not_awaited()
    _mock(bridge.s3).iter_chunks.assert_not_called()


async def test_source_limit_precedes_original_object_read() -> None:
    bridge = dataclasses.replace(_bridge(), maximum_bytes=2)
    source = _vfs(b"body", AsyncMock(return_value=True))
    _mock(bridge.resolver).resolve.return_value = source
    with pytest.raises(GoogleSdkError) as error:
        await bridge.resolve(
            GoogleFileInput(source=source.source_uri, filename=None, media_type=None),
            admit=AsyncMock(),
        )
    assert error.value.code == "file_input_limit"
    _mock(source.revalidate).assert_not_awaited()


async def test_publication_retains_canonical_run_and_safe_file_metadata() -> None:
    bridge = _bridge()
    file = GooglePreparedFile(
        "output.txt", "text/plain", b"generated", ("google-file",)
    )
    artifact = _artifact(file.content).model_copy(update={"name": file.filename})
    _mock(bridge.artifacts).create_for_authority.return_value = Success(artifact)
    admit = AsyncMock()
    result = await bridge.publish(
        (file,), tool_name="drive_read_content", call_id="call", admit=admit
    )
    assert result[0].uri == artifact.uri and result[0].sha256 == file.sha256
    kwargs = _mock(bridge.artifacts).create_for_authority.call_args.kwargs
    assert kwargs["authority"] == _authority()
    assert kwargs["source_call_id"] == "call" and kwargs["source_part_index"] == 0
    assert kwargs["body"] == file.content
    assert kwargs["metadata"] == {"google_source_ids": ["google-file"]}
    assert admit.await_count == 2


async def test_publication_denied_by_canonical_owner_does_not_claim_success() -> None:
    bridge = _bridge()
    _mock(bridge.artifacts).create_for_authority.return_value = Failure(
        ArtifactAccessDenied()
    )
    with pytest.raises(GoogleSdkError) as error:
        await bridge.publish(
            (
                GooglePreparedFile(
                    "output.bin", "application/octet-stream", b"body", ()
                ),
            ),
            tool_name="google",
            call_id="call",
            admit=AsyncMock(),
        )
    assert error.value.code == "file_publication_denied"


async def test_publication_rechecks_authority_before_storage_effect() -> None:
    bridge = _bridge()
    admit = AsyncMock(
        side_effect=GoogleOAuthError(
            "capability_unavailable", "Current Google service disabled."
        )
    )
    with pytest.raises(GoogleOAuthError):
        await bridge.publish(
            (GooglePreparedFile("output.txt", "text/plain", b"body", ()),),
            tool_name="google",
            call_id="call",
            admit=admit,
        )
    _mock(bridge.artifacts).create_for_authority.assert_not_awaited()


async def test_publication_batch_limit_is_validated_before_any_artifact() -> None:
    bridge = dataclasses.replace(_bridge(), maximum_bytes=3)
    with pytest.raises(GoogleSdkError) as error:
        await bridge.publish(
            (GooglePreparedFile("output.txt", "text/plain", b"body", ()),),
            tool_name="google",
            call_id="call",
            admit=AsyncMock(),
        )
    assert error.value.code == "file_publication_limit"
    _mock(bridge.artifacts).create_for_authority.assert_not_awaited()


async def test_partial_publication_preserves_confirmed_uris_without_google_replay() -> (
    None
):
    bridge = _bridge()
    file = GooglePreparedFile("output.txt", "text/plain", b"generated", ())
    artifact = _artifact(file.content)
    _mock(bridge.artifacts).create_for_authority.side_effect = [
        Success(artifact),
        Failure(ArtifactAccessDenied()),
    ]
    with pytest.raises(GoogleWorkspacePartialError) as error:
        await bridge.publish(
            (file, file),
            tool_name="google",
            call_id="call",
            admit=AsyncMock(),
        )
    assert error.value.partial.completed[0].resource_ids == (artifact.uri,)
    assert error.value.partial.remaining_ids == ("1",)
    assert _mock(bridge.artifacts).create_for_authority.await_count == 2
