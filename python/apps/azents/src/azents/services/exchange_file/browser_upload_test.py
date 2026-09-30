"""Browser upload service verification, publication, retry, and cleanup tests."""

import asyncio
import base64
import datetime
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from io import BytesIO
from unittest.mock import Mock, call

import pytest
from azcommon.infra.s3.service import (
    S3ListedMultipartUpload,
    S3MultipartUpload,
    S3MultipartUploadPage,
    S3ObjectIdentity,
    S3ObjectMetadata,
    S3PresignedRequest,
    S3ProductPublicationResult,
    S3Service,
    S3TransferObjectMetadata,
)
from azcommon.result import Failure, Success
from PIL import Image

from azents.core.enums import ExchangeFileOrigin, ExchangeFileProvenanceKind
from azents.core.exchange_upload import ExchangeUploadError, ExchangeUploadState
from azents.repos.exchange_file.operations import (
    ExchangeFileCreateBatch,
    ExchangeFileOperationRepository,
)
from azents.repos.exchange_file.upload_data import ExchangeUploadOperation

from . import CHAT_UPLOAD_MAX_SIZE, ExchangeFileService

_NOW = datetime.datetime(2026, 9, 29, tzinfo=datetime.UTC)
_BODY = b"browser attachment"
_SHA256 = hashlib.sha256(_BODY).hexdigest()


def _operation() -> ExchangeUploadOperation:
    """Create one detached operation with reserved private identities."""
    return ExchangeUploadOperation(
        upload_id="upload-1",
        publication_id="publication-1",
        preview_file_id="preview-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        uploader_user_id="user-1",
        filename="report.bin",
        media_type="application/octet-stream",
        expected_size=len(_BODY),
        expected_sha256=_SHA256,
        created_at=_NOW,
        expires_at=_NOW + datetime.timedelta(minutes=15),
        cleanup_after=_NOW + datetime.timedelta(minutes=30),
        state=ExchangeUploadState.PENDING,
        finalize_claim_id=None,
        finalize_lease_until=None,
        finalized_at=None,
        cleanup_claim_id=None,
        cleanup_lease_until=None,
        cleanup_completed_at=None,
    )


def _identity(kind: str) -> S3ObjectIdentity:
    """Derive fixture object ownership independently from the service helper."""
    return S3ObjectIdentity(
        bucket="test-bucket", key=f"exchange-uploads/workspace-1/upload-1/{kind}"
    )


def _metadata(identity: S3ObjectIdentity) -> S3ObjectMetadata:
    """Build authoritative exact-size storage checksum evidence."""
    return S3ObjectMetadata(
        identity=identity,
        content_length=len(_BODY),
        content_type="application/octet-stream",
        etag="opaque-etag-not-a-digest",
        checksum_sha256=base64.b64encode(bytes.fromhex(_SHA256)).decode("ascii"),
        user_metadata={},
        last_modified_at=_NOW,
    )


@dataclass(frozen=True)
class _Fixture:
    """Expose narrowly mocked external boundaries and the real service."""

    service: ExchangeFileService
    repository: Mock
    s3: Mock
    trace: Mock


def _install_stream(s3: Mock, body: bytes) -> None:
    """Supply an observable bounded stream without mocking preview processing."""

    @asynccontextmanager
    async def stream(
        identity: S3ObjectIdentity, *, maximum_chunk_size: int
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        assert identity == _identity("source")
        assert maximum_chunk_size == 64 * 1024

        async def chunks() -> AsyncIterator[bytes]:
            for offset in range(0, len(body), 4):
                yield body[offset : offset + 4]

        yield chunks()

    s3.iter_chunks.side_effect = stream


def _fixture(operation: ExchangeUploadOperation) -> _Fixture:
    """Keep manifest preparation, verification, and publication logic real."""
    repository = Mock(spec=ExchangeFileOperationRepository)
    repository.prepare_agent_upload_operation.return_value = Success(operation)
    repository.claim_agent_upload_operation.return_value = Success(operation)
    repository.finalize_agent_upload_operation.return_value = Success("published")
    repository.load_agent_upload_publication.return_value = Success("published")
    repository.claim_due_agent_upload_cleanup.return_value = [operation]
    repository.finish_agent_upload_cleanup.return_value = True
    s3 = Mock(spec=S3Service)
    _install_stream(s3, _BODY)
    s3.head.return_value = None
    s3.head_with_checksum.return_value = _metadata(_identity("ingress"))
    s3.copy_verified_transfer_object_to_product.return_value = (
        S3ProductPublicationResult(
            metadata=_metadata(_identity("source")), created=True
        )
    )
    s3.get_upload_request.return_value = S3PresignedRequest(
        method="PUT",
        url="https://objects.example/put?signature=transient",
        expires_at=_NOW + datetime.timedelta(minutes=5),
        headers={
            "content-type": operation.media_type,
            "x-amz-checksum-sha256": base64.b64encode(
                bytes.fromhex(operation.expected_sha256)
            ).decode("ascii"),
        },
    )
    s3.list_multipart_uploads_page.return_value = S3MultipartUploadPage(
        uploads=(), next_key_marker=None, next_upload_id_marker=None, skipped_entries=0
    )
    trace = Mock()
    trace.attach_mock(repository, "repository")
    trace.attach_mock(s3, "s3")
    config = Mock()
    config.workspace_s3.bucket = "test-bucket"
    config.general_file_maximum_bytes = CHAT_UPLOAD_MAX_SIZE
    config.file_lifecycle.exchange_file_ttl = datetime.timedelta(days=7)
    service = ExchangeFileService(
        operation_repository=repository,
        exchange_file_repository=Mock(),
        agent_session_repository=Mock(),
        workspace_user_repository=Mock(),
        s3_service=s3,
        config=config,
    )
    return _Fixture(service=service, repository=repository, s3=s3, trace=trace)


async def _finalize(fixture: _Fixture) -> object:
    """Finalize through the public service boundary."""
    return await fixture.service.finalize_agent_browser_upload(
        agent_id="agent-1", user_id="user-1", upload_id="upload-1"
    )


@pytest.mark.parametrize("size", [15, 16, 17])
async def test_prepare_uses_injected_small_limit_before_authorization_and_presign(
    size: int,
) -> None:
    """Small boundary fixtures exercise effective admission without large bodies."""
    operation = replace(_operation(), expected_size=size)
    fixture = _fixture(operation)
    fixture.service.config.general_file_maximum_bytes = 16
    result = await fixture.service.prepare_agent_browser_upload(
        agent_id=operation.agent_id,
        user_id=operation.uploader_user_id,
        filename=operation.filename,
        media_type=operation.media_type,
        size=size,
        sha256=operation.expected_sha256,
    )
    if size <= 16:
        assert isinstance(result, Success)
        assert (
            fixture.repository.prepare_agent_upload_operation.call_args.kwargs[
                "expected_size"
            ]
            == size
        )
        assert fixture.s3.get_upload_request.call_args.kwargs["content_length"] == size
    else:
        assert result == Failure(ExchangeUploadError.INVALID_REQUEST)
        fixture.repository.prepare_agent_upload_operation.assert_not_awaited()
        fixture.s3.get_upload_request.assert_not_awaited()


async def test_prepare_authorizes_manifest_before_exact_put_ticket() -> None:
    """Only persisted ownership and manifest values determine the PUT capability."""
    operation = _operation()
    fixture = _fixture(operation)
    result = await fixture.service.prepare_agent_browser_upload(
        agent_id=operation.agent_id,
        user_id=operation.uploader_user_id,
        filename="../report.bin",
        media_type=operation.media_type,
        size=operation.expected_size,
        sha256=operation.expected_sha256,
    )
    assert isinstance(result, Success)
    assert result.value.upload_id == operation.upload_id
    assert result.value.request is fixture.s3.get_upload_request.return_value
    manifest = fixture.repository.prepare_agent_upload_operation.call_args.kwargs
    assert manifest["agent_id"] == operation.agent_id
    assert manifest["user_id"] == operation.uploader_user_id
    assert manifest["filename"] == "_report.bin"
    assert manifest["expected_size"] == len(_BODY)
    assert manifest["expected_sha256"] == _SHA256
    assert manifest["expires_at"] - manifest["now"] == datetime.timedelta(minutes=15)
    assert manifest["cleanup_after"] - manifest["expires_at"] == datetime.timedelta(
        minutes=15
    )
    fixture.s3.get_upload_request.assert_awaited_once_with(
        identity=_identity("ingress"),
        content_type=operation.media_type,
        content_length=len(_BODY),
        checksum_sha256=_SHA256,
        expires_in=datetime.timedelta(minutes=5),
        now=manifest["now"],
    )
    assert "content-length" not in result.value.request.headers
    assert [item[0] for item in fixture.trace.mock_calls] == [
        "repository.prepare_agent_upload_operation",
        "s3.get_upload_request",
    ]


@pytest.mark.parametrize(
    ("size", "media_type"),
    [
        (-1, "text/plain"),
        (CHAT_UPLOAD_MAX_SIZE + 1, "text/plain"),
        (True, "text/plain"),
        (1, ""),
        (1, "text/plain\r\ninjected"),
    ],
)
async def test_prepare_rejects_invalid_manifest_before_repository(
    size: int, media_type: str
) -> None:
    """Invalid caller metadata never reaches authorization or presigning."""
    fixture = _fixture(_operation())
    result = await fixture.service.prepare_agent_browser_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.txt",
        media_type=media_type,
        size=size,
        sha256=_SHA256,
    )
    assert result == Failure(ExchangeUploadError.INVALID_REQUEST)
    fixture.repository.prepare_agent_upload_operation.assert_not_awaited()
    fixture.s3.get_upload_request.assert_not_awaited()


@pytest.mark.parametrize(
    "error", [ExchangeUploadError.NOT_FOUND, ExchangeUploadError.ACCESS_DENIED]
)
async def test_prepare_authority_failure_never_issues_ticket(
    error: ExchangeUploadError,
) -> None:
    """Rejected Agent ownership does not disclose a storage capability."""
    fixture = _fixture(_operation())
    fixture.repository.prepare_agent_upload_operation.return_value = Failure(error)
    result = await fixture.service.prepare_agent_browser_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.bin",
        media_type="application/octet-stream",
        size=len(_BODY),
        sha256=_SHA256,
    )
    assert result == Failure(error)
    fixture.s3.get_upload_request.assert_not_awaited()


async def test_finalize_verifies_before_blob_and_metadata_publication() -> None:
    """The verified exact source, not ingress or buffered bytes, becomes Exchange."""
    fixture = _fixture(_operation())
    assert await _finalize(fixture) == Success("published")
    fixture.s3.copy_immutable.assert_awaited_once_with(
        source=_identity("ingress"),
        destination=_identity("source"),
        expected_size=len(_BODY),
        transfer_metadata=S3TransferObjectMetadata(
            sha256=_SHA256, content_type="application/octet-stream"
        ),
        multipart_copy_threshold=CHAT_UPLOAD_MAX_SIZE,
        multipart_part_size=8 * 1024 * 1024,
    )
    fixture.s3.verify_transfer_object.assert_awaited_once_with(
        identity=_identity("source"),
        expected_size=len(_BODY),
        expected_sha256=_SHA256,
    )
    publication = fixture.s3.copy_verified_transfer_object_to_product.call_args.kwargs
    assert publication["source"] == _identity("source")
    assert publication["destination"] == S3ObjectIdentity(
        bucket="test-bucket", key="exchange/workspace-1/files/publication-1/original"
    )
    assert publication["expected_size"] == len(_BODY)
    assert publication["publication_metadata"].publication_id == "publication-1"
    assert publication["publication_metadata"].sha256 == _SHA256
    batch = fixture.repository.finalize_agent_upload_operation.call_args.kwargs["batch"]
    assert isinstance(batch, ExchangeFileCreateBatch)
    assert batch.source.id == "publication-1"
    assert batch.source.sha256 == _SHA256
    assert batch.source.size_bytes == len(_BODY)
    assert batch.source.origin_type is ExchangeFileOrigin.UPLOAD
    assert batch.source.provenance_kind is ExchangeFileProvenanceKind.HUMAN
    assert batch.source.source_user_id == "user-1"
    assert batch.source.retention_root_session_id is None
    assert batch.preview is None
    assert [item[0] for item in fixture.trace.mock_calls] == [
        "repository.claim_agent_upload_operation",
        "s3.head",
        "s3.head_with_checksum",
        "s3.copy_immutable",
        "s3.verify_transfer_object",
        "s3.iter_chunks",
        "s3.copy_verified_transfer_object_to_product",
        "repository.finalize_agent_upload_operation",
        "repository.release_agent_upload_claim",
    ]
    claim = fixture.repository.claim_agent_upload_operation.call_args.kwargs
    commit = fixture.repository.finalize_agent_upload_operation.call_args.kwargs
    assert claim["user_id"] == commit["user_id"] == "user-1"
    assert claim["claim_id"] == commit["claim_id"]
    fixture.repository.release_agent_upload_claim.assert_awaited_once_with(
        upload_id="upload-1", claim_id=claim["claim_id"]
    )
    fixture.s3.upload.assert_not_awaited()
    fixture.s3.delete.assert_not_awaited()


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        replace(_metadata(_identity("ingress")), content_length=999),
        replace(_metadata(_identity("ingress")), content_type="text/plain"),
        replace(_metadata(_identity("ingress")), checksum_sha256=None),
        replace(_metadata(_identity("ingress")), checksum_sha256="wrong-checksum"),
    ],
)
async def test_finalize_rejects_missing_or_mismatched_storage_evidence(
    metadata: S3ObjectMetadata | None,
) -> None:
    """ETags or browser assertions never substitute for storage SHA-256 evidence."""
    fixture = _fixture(_operation())
    fixture.s3.head_with_checksum.return_value = metadata
    assert await _finalize(fixture) == Failure(ExchangeUploadError.MANIFEST_MISMATCH)
    fixture.s3.copy_immutable.assert_not_awaited()
    fixture.s3.copy_verified_transfer_object_to_product.assert_not_awaited()
    fixture.repository.finalize_agent_upload_operation.assert_not_awaited()
    fixture.repository.release_agent_upload_claim.assert_awaited_once()


@pytest.mark.parametrize("failure", [FileNotFoundError(), ValueError("mismatch")])
async def test_finalize_source_verification_failure_prevents_publication(
    failure: Exception,
) -> None:
    """A copied source still requires independent trusted verification."""
    fixture = _fixture(_operation())
    fixture.s3.verify_transfer_object.side_effect = failure
    assert await _finalize(fixture) == Failure(ExchangeUploadError.MANIFEST_MISMATCH)
    fixture.s3.copy_verified_transfer_object_to_product.assert_not_awaited()
    fixture.repository.finalize_agent_upload_operation.assert_not_awaited()
    fixture.repository.release_agent_upload_claim.assert_awaited_once()
    fixture.s3.delete.assert_not_awaited()


@pytest.mark.parametrize(
    "failure", [RuntimeError("storage unavailable"), asyncio.CancelledError()]
)
async def test_finalize_propagates_unexpected_failure_and_cancellation(
    failure: BaseException,
) -> None:
    """Storage errors and cancellation stay observable while releasing the claim."""
    fixture = _fixture(_operation())
    fixture.s3.copy_verified_transfer_object_to_product.side_effect = failure
    with pytest.raises(type(failure)):
        await _finalize(fixture)
    fixture.repository.finalize_agent_upload_operation.assert_not_awaited()
    fixture.repository.release_agent_upload_claim.assert_awaited_once()
    fixture.s3.delete.assert_not_awaited()


async def test_finalize_retry_reuses_but_reverifies_existing_source() -> None:
    """A retry ignores overwritten ingress once an operation source is reserved."""
    fixture = _fixture(_operation())
    fixture.s3.head.return_value = _metadata(_identity("source"))
    assert await _finalize(fixture) == Success("published")
    fixture.s3.head_with_checksum.assert_not_awaited()
    fixture.s3.copy_immutable.assert_not_awaited()
    fixture.s3.verify_transfer_object.assert_awaited_once()


async def test_finalize_reverifies_source_created_by_prior_claim() -> None:
    """An immutable-copy collision is not evidence of matching uploaded bytes."""
    fixture = _fixture(_operation())
    fixture.s3.copy_immutable.side_effect = FileExistsError()
    assert await _finalize(fixture) == Success("published")
    fixture.s3.verify_transfer_object.assert_awaited_once()


async def test_finalize_published_loads_current_authorized_publication() -> None:
    """Idempotency uses current repository authorization without touching storage."""
    fixture = _fixture(
        replace(_operation(), state=ExchangeUploadState.FINALIZED, finalized_at=_NOW)
    )
    assert await _finalize(fixture) == Success("published")
    fixture.repository.load_agent_upload_publication.assert_awaited_once_with(
        agent_id="agent-1",
        user_id="user-1",
        upload_id="upload-1",
        now=fixture.repository.claim_agent_upload_operation.call_args.kwargs["now"],
    )
    assert fixture.s3.mock_calls == []


@pytest.mark.parametrize("error", list(ExchangeUploadError))
async def test_finalize_rejected_claim_performs_no_storage_work(
    error: ExchangeUploadError,
) -> None:
    """Not-found, denied, expired, and fenced callers cannot publish."""
    fixture = _fixture(_operation())
    fixture.repository.claim_agent_upload_operation.return_value = Failure(error)
    assert await _finalize(fixture) == Failure(error)
    assert fixture.s3.mock_calls == []
    fixture.repository.release_agent_upload_claim.assert_not_awaited()


async def test_finalize_failed_metadata_commit_preserves_retry_objects() -> None:
    """Uncertain or fenced commits do not delete operation-owned evidence."""
    fixture = _fixture(_operation())
    fixture.repository.finalize_agent_upload_operation.return_value = Failure(
        ExchangeUploadError.FENCED
    )
    assert await _finalize(fixture) == Failure(ExchangeUploadError.FENCED)
    fixture.s3.delete.assert_not_awaited()
    fixture.repository.release_agent_upload_claim.assert_awaited_once()


async def test_finalize_text_preview_reads_only_bounded_stream_chunks() -> None:
    """Original metadata preserves the complete manifest and streamed preview."""
    fixture = _fixture(
        replace(_operation(), filename="report.txt", media_type="text/plain")
    )
    fixture.s3.head.return_value = _metadata(_identity("source"))

    assert await _finalize(fixture) == Success("published")
    batch = fixture.repository.finalize_agent_upload_operation.call_args.kwargs["batch"]
    assert batch.source.preview_summary == _BODY.decode()
    assert batch.source.size_bytes == len(_BODY)
    assert batch.source.sha256 == _SHA256


async def test_finalize_streams_reserved_image_preview() -> None:
    """Generated thumbnails use reserved identities without changing the original."""
    buffer = BytesIO()
    Image.new("RGBA", (600, 300), color=(255, 0, 0, 128)).save(buffer, format="PNG")
    body = buffer.getvalue()
    digest = hashlib.sha256(body).hexdigest()
    fixture = _fixture(
        replace(
            _operation(),
            filename="report.png",
            media_type="image/png",
            expected_size=len(body),
            expected_sha256=digest,
        )
    )
    fixture.s3.head.return_value = _metadata(_identity("source"))
    _install_stream(fixture.s3, body)
    assert await _finalize(fixture) == Success("published")
    batch = fixture.repository.finalize_agent_upload_operation.call_args.kwargs["batch"]
    assert isinstance(batch, ExchangeFileCreateBatch)
    assert batch.source.id == "publication-1"
    assert batch.source.size_bytes == len(body)
    assert batch.source.sha256 == digest
    assert batch.preview is not None
    assert batch.preview.create.id == "preview-1"
    assert batch.preview.create.provenance_kind is ExchangeFileProvenanceKind.PREVIEW
    assert batch.preview.create.source_exchange_file_id == "publication-1"
    assert batch.preview.create.source_user_id is None
    assert batch.preview.width == 512
    assert batch.preview.height == 256
    uploaded = fixture.s3.upload.call_args.kwargs
    assert uploaded["key"] == "exchange/workspace-1/files/preview-1/original"
    assert uploaded["content_type"] == "image/jpeg"
    assert hashlib.sha256(uploaded["body"]).hexdigest() == batch.preview.create.sha256
    assert len(uploaded["body"]) == batch.preview.create.size_bytes
    order = [item[0] for item in fixture.trace.mock_calls]
    assert order.index("s3.verify_transfer_object") < order.index("s3.iter_chunks")
    assert order.index("s3.upload") < order.index(
        "repository.finalize_agent_upload_operation"
    )


async def test_finalize_large_image_skips_independent_thumbnail_budget() -> None:
    """Accepted Chat size does not implicitly enlarge the image-processing budget."""
    fixture = _fixture(
        replace(
            _operation(),
            filename="large.png",
            media_type="image/png",
            expected_size=20 * 1024 * 1024 + 1,
        )
    )
    fixture.s3.head.return_value = _metadata(_identity("source"))
    assert await _finalize(fixture) == Success("published")
    fixture.s3.iter_chunks.assert_not_called()
    fixture.s3.upload.assert_not_awaited()
    batch = fixture.repository.finalize_agent_upload_operation.call_args.kwargs["batch"]
    assert batch.source.size_bytes == 20 * 1024 * 1024 + 1
    assert batch.preview is None


@pytest.mark.parametrize("suffix", [b"\xff", b"\x00"])
async def test_finalize_drops_preview_if_late_stream_data_is_binary(
    suffix: bytes,
) -> None:
    """Validation continues past the preview limit rather than trusting its prefix."""
    body = b"a" * 2100 + suffix
    fixture = _fixture(
        replace(
            _operation(),
            filename="report.txt",
            media_type="text/plain",
            expected_size=len(body),
            expected_sha256=hashlib.sha256(body).hexdigest(),
        )
    )
    fixture.s3.head.return_value = _metadata(_identity("source"))
    _install_stream(fixture.s3, body)
    assert await _finalize(fixture) == Success("published")
    batch = fixture.repository.finalize_agent_upload_operation.call_args.kwargs["batch"]
    assert batch.source.preview_summary is None
    assert batch.source.size_bytes == len(body)


@pytest.mark.parametrize("finalized", [False, True])
async def test_cleanup_deletes_only_reserved_objects_and_bounds_claim(
    finalized: bool,
) -> None:
    """Finalized publication survives residue collection; pending copies do not."""
    operation = _operation()
    if finalized:
        operation = replace(
            operation, state=ExchangeUploadState.FINALIZED, finalized_at=_NOW
        )
    fixture = _fixture(operation)
    assert await fixture.service.cleanup_agent_browser_uploads(limit=7) == 1
    claim = fixture.repository.claim_due_agent_upload_cleanup.call_args.kwargs
    assert claim["limit"] == 7
    assert claim["lease_until"] - claim["now"] == datetime.timedelta(minutes=5)
    expected_keys = [_identity("ingress").key, _identity("source").key]
    if not finalized:
        expected_keys.extend(
            [
                "exchange/workspace-1/files/publication-1/original",
                "exchange/workspace-1/files/preview-1/original",
            ]
        )
    assert fixture.s3.delete.await_args_list == [
        call(bucket="test-bucket", key=key) for key in expected_keys
    ]
    for item in fixture.s3.list_multipart_uploads_page.await_args_list:
        assert item.kwargs["maximum_uploads"] == 100
        assert item.kwargs["key_marker"] is None
        assert item.kwargs["upload_id_marker"] is None
    fixture.repository.finish_agent_upload_cleanup.assert_awaited_once_with(
        upload_id=operation.upload_id, claim_id=claim["claim_id"]
    )


async def test_repeated_finalized_cleanup_removes_late_put_but_keeps_publication() -> (
    None
):
    """A completed operation still owns late ingress, never its committed family."""
    operation = replace(
        _operation(), state=ExchangeUploadState.FINALIZED, finalized_at=_NOW
    )
    fixture = _fixture(operation)
    publication_key = "exchange/workspace-1/files/publication-1/original"
    preview_key = "exchange/workspace-1/files/preview-1/original"
    stored = {
        publication_key: b"published-original",
        preview_key: b"published-thumbnail",
        _identity("ingress").key: _BODY,
        _identity("source").key: _BODY,
    }

    async def delete(*, bucket: str, key: str) -> None:
        assert bucket == "test-bucket"
        stored.pop(key, None)

    fixture.s3.delete.side_effect = delete
    assert await fixture.service.cleanup_agent_browser_uploads(limit=1) == 1
    assert set(stored) == {publication_key, preview_key}
    completed = _NOW + datetime.timedelta(minutes=30)
    fixture.repository.claim_due_agent_upload_cleanup.return_value = [
        replace(
            operation,
            cleanup_completed_at=completed,
            cleanup_after=completed + datetime.timedelta(hours=1),
        )
    ]
    stored[_identity("ingress").key] = b"PUT completed after initial cleanup"
    assert await fixture.service.cleanup_agent_browser_uploads(limit=1) == 1
    assert stored == {
        publication_key: b"published-original",
        preview_key: b"published-thumbnail",
    }
    assert fixture.s3.delete.await_args_list == [
        call(bucket="test-bucket", key=_identity(kind).key)
        for kind in ("ingress", "source", "ingress", "source")
    ]
    assert fixture.repository.finish_agent_upload_cleanup.await_count == 2


async def test_cleanup_aborts_only_exact_owned_multipart_uploads() -> None:
    """Prefix neighbors are never mistaken for operation-owned objects."""
    fixture = _fixture(_operation())
    exact = S3MultipartUpload(identity=_identity("ingress"), upload_id="owned")
    neighbor = S3MultipartUpload(
        identity=S3ObjectIdentity(
            bucket="test-bucket", key=_identity("ingress").key + "-other"
        ),
        upload_id="unowned",
    )
    fixture.s3.list_multipart_uploads_page.side_effect = [
        S3MultipartUploadPage(
            uploads=(
                S3ListedMultipartUpload(upload=exact, initiated_at=_NOW),
                S3ListedMultipartUpload(upload=neighbor, initiated_at=_NOW),
            ),
            next_key_marker=None,
            next_upload_id_marker=None,
            skipped_entries=0,
        ),
        *[
            S3MultipartUploadPage(
                uploads=(),
                next_key_marker=None,
                next_upload_id_marker=None,
                skipped_entries=0,
            )
        ]
        * 3,
    ]
    assert await fixture.service.cleanup_agent_browser_uploads(limit=1) == 1
    fixture.s3.abort_multipart_upload.assert_awaited_once_with(upload=exact)


async def test_cleanup_paginated_residue_defers_completion_to_next_pass() -> None:
    """A full listing page is bounded and never marks incomplete cleanup done."""
    fixture = _fixture(_operation())
    fixture.s3.list_multipart_uploads_page.return_value = S3MultipartUploadPage(
        uploads=(),
        next_key_marker="more",
        next_upload_id_marker="more-upload",
        skipped_entries=0,
    )
    assert await fixture.service.cleanup_agent_browser_uploads(limit=1) == 0
    fixture.s3.list_multipart_uploads_page.assert_awaited_once()
    fixture.s3.delete.assert_not_awaited()
    fixture.repository.finish_agent_upload_cleanup.assert_not_awaited()


async def test_cleanup_skipped_listing_entries_preserve_durable_retry() -> None:
    """Malformed listing evidence cannot authorize deletion or completed cleanup."""
    fixture = _fixture(_operation())
    fixture.s3.list_multipart_uploads_page.return_value = S3MultipartUploadPage(
        uploads=(),
        next_key_marker=None,
        next_upload_id_marker=None,
        skipped_entries=1,
    )
    assert await fixture.service.cleanup_agent_browser_uploads(limit=1) == 0
    fixture.s3.list_multipart_uploads_page.assert_awaited_once()
    fixture.s3.delete.assert_not_awaited()
    fixture.repository.finish_agent_upload_cleanup.assert_not_awaited()


async def test_cleanup_failed_deletion_does_not_mark_complete() -> None:
    """Storage errors retain durable retry ownership and remain observable."""
    fixture = _fixture(_operation())
    fixture.s3.delete.side_effect = RuntimeError("storage unavailable")
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await fixture.service.cleanup_agent_browser_uploads(limit=1)
    fixture.repository.finish_agent_upload_cleanup.assert_not_awaited()
