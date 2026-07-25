"""Tests for bounded S3 transfer operations."""

import asyncio
import hashlib
from dataclasses import dataclass
from typing import cast

import pytest
from botocore.exceptions import ClientError

from azcommon.infra.s3.service import (
    S3CompletedPart,
    S3MultipartUpload,
    S3ObjectIdentity,
    S3Service,
    S3TransferObjectMetadata,
)


@dataclass
class _StoredObject:
    body: bytes
    metadata: dict[str, str]
    content_type: str | None
    checksum_sha256: str | None = None


class _Body:
    """In-memory S3 response body with explicit close evidence."""

    def __init__(self, body: bytes) -> None:
        """Initialize the body.

        :param body: Bytes returned by the fake object store.
        """
        self.body = body
        self.offset = 0
        self.closed = False
        self.read_sizes: list[int | None] = []

    async def read(self, amt: int | None = None) -> bytes:
        """Read the requested number of bytes.

        :param amt: Optional maximum byte count.
        :returns: Next body bytes.
        """
        self.read_sizes.append(amt)
        if self.offset >= len(self.body):
            return b""
        end = len(self.body) if amt is None else self.offset + amt
        result = self.body[self.offset : end]
        self.offset += len(result)
        return result

    def close(self) -> None:
        """Record response-body closure."""
        self.closed = True


class _FailingBody(_Body):
    """Response body that fails its first read."""

    async def read(self, amt: int | None = None) -> bytes:
        """Raise one deterministic read failure."""
        self.read_sizes.append(amt)
        raise RuntimeError("read failed")


class _BlockingBody(_Body):
    """Response body that blocks until its reader is cancelled."""

    def __init__(self, body: bytes) -> None:
        """Initialize cancellation synchronization."""
        super().__init__(body)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def read(self, amt: int | None = None) -> bytes:
        """Wait for release while exposing that the read started."""
        self.read_sizes.append(amt)
        self.started.set()
        await self.release.wait()
        return b""


class _FakeS3Client:
    """Small stateful S3 fake for transfer-safe operation tests."""

    def __init__(self) -> None:
        """Initialize empty object and multipart state."""
        self.objects: dict[tuple[str, str], _StoredObject] = {}
        self.uploads: dict[str, dict[str, object]] = {}
        self.bodies: list[_Body] = []
        self.next_body: _Body | None = None
        self.copy_requests: list[dict[str, object]] = []
        self.block_copy = False
        self.copy_started = asyncio.Event()
        self.copy_release = asyncio.Event()
        self.abort_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.list_calls: list[str | None] = []
        self.list_snapshot: list[str] | None = None
        self.fail_complete = False
        self.complete_then_raise = False
        self.block_complete = False
        self.complete_started = asyncio.Event()
        self.complete_release = asyncio.Event()
        self.fail_upload_part_number: int | None = None
        self.head_error_code: str | None = None
        self.mutate_source_before_copy: bytes | None = None
        self.mutate_source_before_part_copy: bytes | None = None
        self.failed_delete_keys: set[str] = set()
        self.next_upload_id = 1

    async def head_object(self, **arguments: object) -> dict[str, object]:
        """Return one object HEAD response."""
        if self.head_error_code is not None:
            raise _client_error(self.head_error_code)
        bucket = _string_argument(arguments, "Bucket")
        key = _string_argument(arguments, "Key")
        stored = self.objects.get((bucket, key))
        if stored is None:
            raise _client_error("404")
        return {
            "ContentLength": len(stored.body),
            "ContentType": stored.content_type,
            "Metadata": dict(stored.metadata),
            "ETag": f'"{_sha256(stored.body)}"',
            "ChecksumSHA256": stored.checksum_sha256,
        }

    async def get_object(self, **arguments: object) -> dict[str, object]:
        """Return one closable fake response body."""
        bucket = _string_argument(arguments, "Bucket")
        key = _string_argument(arguments, "Key")
        stored = self.objects.get((bucket, key))
        if stored is None:
            raise _client_error("NoSuchKey")
        body = self.next_body or _Body(stored.body)
        self.next_body = None
        self.bodies.append(body)
        return {"Body": body}

    async def copy_object(self, **arguments: object) -> dict[str, object]:
        """Copy an object while recording replacement metadata."""
        self.copy_requests.append(dict(arguments))
        destination = (
            _string_argument(arguments, "Bucket"),
            _string_argument(arguments, "Key"),
        )
        existing = self.objects.get(destination)
        if (
            existing is not None
            and "azents-transfer-reservation" not in existing.metadata
        ):
            raise _client_error("AlreadyExists")
        copy_source = _object_argument(arguments, "CopySource")
        source = (
            _string_argument(copy_source, "Bucket"),
            _string_argument(copy_source, "Key"),
        )
        if self.mutate_source_before_copy is not None:
            original = self.objects[source]
            self.objects[source] = _StoredObject(
                self.mutate_source_before_copy,
                original.metadata,
                original.content_type,
                original.checksum_sha256,
            )
            self.mutate_source_before_copy = None
        source_object = self.objects[source]
        if arguments.get("CopySourceIfMatch") != f'"{_sha256(source_object.body)}"':
            raise _client_error("PreconditionFailed")
        if self.block_copy:
            self.copy_started.set()
            await self.copy_release.wait()
        metadata = _string_mapping_argument(arguments, "Metadata")
        content_type = _optional_string_argument(arguments, "ContentType")
        self.objects[destination] = _StoredObject(
            body=source_object.body,
            metadata=metadata,
            content_type=content_type,
        )
        return {}

    async def create_multipart_upload(self, **arguments: object) -> dict[str, object]:
        """Create one fake multipart upload."""
        upload_id = f"upload-{self.next_upload_id}"
        self.next_upload_id += 1
        self.uploads[upload_id] = {
            "bucket": _string_argument(arguments, "Bucket"),
            "key": _string_argument(arguments, "Key"),
            "metadata": _string_mapping_argument(arguments, "Metadata"),
            "content_type": _optional_string_argument(arguments, "ContentType"),
            "parts": {},
        }
        return {"UploadId": upload_id}

    async def upload_part(self, **arguments: object) -> dict[str, object]:
        """Save one fake multipart body part."""
        upload = self.uploads[_string_argument(arguments, "UploadId")]
        parts = _parts(upload)
        part_number = _integer_argument(arguments, "PartNumber")
        if part_number == self.fail_upload_part_number:
            raise RuntimeError("part failed")
        body = _bytes_argument(arguments, "Body")
        parts[part_number] = body
        return {"ETag": f"etag-{part_number}"}

    async def upload_part_copy(self, **arguments: object) -> dict[str, object]:
        """Copy one source range into a fake multipart upload."""
        upload = self.uploads[_string_argument(arguments, "UploadId")]
        copy_source = _object_argument(arguments, "CopySource")
        source = (
            _string_argument(copy_source, "Bucket"),
            _string_argument(copy_source, "Key"),
        )
        if self.mutate_source_before_part_copy is not None:
            original = self.objects[source]
            self.objects[source] = _StoredObject(
                self.mutate_source_before_part_copy,
                original.metadata,
                original.content_type,
                original.checksum_sha256,
            )
            self.mutate_source_before_part_copy = None
        source_object = self.objects[source]
        if arguments.get("CopySourceIfMatch") != f'"{_sha256(source_object.body)}"':
            raise _client_error("PreconditionFailed")
        byte_range = _string_argument(arguments, "CopySourceRange")
        start_text, end_text = byte_range.removeprefix("bytes=").split("-", 1)
        part_number = _integer_argument(arguments, "PartNumber")
        _parts(upload)[part_number] = source_object.body[
            int(start_text) : int(end_text) + 1
        ]
        return {"CopyPartResult": {"ETag": f"copy-etag-{part_number}"}}

    async def complete_multipart_upload(self, **arguments: object) -> dict[str, object]:
        """Complete one fake multipart upload or fail deterministically."""
        if self.block_complete:
            self.complete_started.set()
            await self.complete_release.wait()
        if self.fail_complete:
            raise RuntimeError("complete failed")
        upload_id = _string_argument(arguments, "UploadId")
        upload = self.uploads[upload_id]
        bucket = _string_value(upload, "bucket")
        key = _string_value(upload, "key")
        if arguments.get("IfNoneMatch") == "*" and (bucket, key) in self.objects:
            raise _client_error("PreconditionFailed")
        self.uploads.pop(upload_id)
        self.objects[(bucket, key)] = _StoredObject(
            body=b"".join(_parts(upload)[number] for number in sorted(_parts(upload))),
            metadata=_string_mapping_value(upload, "metadata"),
            content_type=_optional_string_value(upload, "content_type"),
        )
        if self.complete_then_raise:
            raise RuntimeError("ambiguous completion")
        return {}

    async def abort_multipart_upload(self, **arguments: object) -> dict[str, object]:
        """Abort one fake multipart upload."""
        upload_id = _string_argument(arguments, "UploadId")
        self.abort_calls.append(upload_id)
        self.uploads.pop(upload_id, None)
        return {}

    async def put_object(self, **arguments: object) -> dict[str, object]:
        """Put one fake object."""
        identity = (
            _string_argument(arguments, "Bucket"),
            _string_argument(arguments, "Key"),
        )
        if arguments.get("IfNoneMatch") == "*" and identity in self.objects:
            raise _client_error("PreconditionFailed")
        self.objects[identity] = _StoredObject(
            body=_bytes_argument(arguments, "Body"),
            metadata=_string_mapping_argument(arguments, "Metadata"),
            content_type=_optional_string_argument(arguments, "ContentType"),
        )
        return {}

    async def delete_object(self, **arguments: object) -> dict[str, object]:
        """Delete one fake object."""
        key = _string_argument(arguments, "Key")
        self.delete_calls.append(key)
        self.objects.pop((_string_argument(arguments, "Bucket"), key), None)
        return {}

    async def list_objects_v2(self, **arguments: object) -> dict[str, object]:
        """Return an ordered bounded key page."""
        bucket = _string_argument(arguments, "Bucket")
        prefix = _string_argument(arguments, "Prefix")
        maximum_keys = _integer_argument(arguments, "MaxKeys")
        token = _optional_string_argument(arguments, "ContinuationToken")
        self.list_calls.append(token)
        if token is None:
            self.list_snapshot = sorted(
                key
                for object_bucket, key in self.objects
                if object_bucket == bucket and key.startswith(prefix)
            )
        if self.list_snapshot is None:
            raise AssertionError("continuation token requires an initial page")
        keys = self.list_snapshot
        start = int(token) if token is not None else 0
        page = keys[start : start + maximum_keys]
        next_start = start + len(page)
        return {
            "Contents": [{"Key": key} for key in page],
            "NextContinuationToken": str(next_start)
            if next_start < len(keys)
            else None,
        }

    async def delete_objects(self, **arguments: object) -> dict[str, object]:
        """Delete a bounded batch and preserve configured per-key failures."""
        bucket = _string_argument(arguments, "Bucket")
        delete = _object_argument(arguments, "Delete")
        objects = delete.get("Objects")
        if not isinstance(objects, list):
            raise AssertionError("Delete Objects must be a list")
        object_entries = cast(list[object], objects)
        deleted: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []
        for item in object_entries:
            if not isinstance(item, dict):
                raise AssertionError("Delete object must be a mapping")
            key = _string_argument(cast(dict[str, object], item), "Key")
            if key in self.failed_delete_keys:
                errors.append({"Key": key})
            else:
                self.objects.pop((bucket, key), None)
                deleted.append({"Key": key})
        return {"Deleted": deleted, "Errors": errors}


def _service(client: _FakeS3Client) -> S3Service:
    """Construct S3Service without requiring the full generated SDK interface."""
    service = object.__new__(S3Service)
    service.s3_client = client
    service.public_s3_client = client
    return service


def _client_error(code: str) -> ClientError:
    """Build one S3 client error.

    :param code: S3 error code.
    :returns: Client error carrying that code.
    """
    return ClientError({"Error": {"Code": code}}, "test")


def _object_argument(arguments: dict[str, object], name: str) -> dict[str, object]:
    """Return a mapping argument with strict test validation."""
    value = arguments[name]
    if not isinstance(value, dict):
        raise AssertionError(f"{name} must be a mapping")
    return cast(dict[str, object], value)


def _string_argument(arguments: dict[str, object], name: str) -> str:
    """Return a required string argument."""
    value = arguments[name]
    if not isinstance(value, str):
        raise AssertionError(f"{name} must be a string")
    return value


def _optional_string_argument(arguments: dict[str, object], name: str) -> str | None:
    """Return one optional string argument."""
    value = arguments.get(name)
    if value is not None and not isinstance(value, str):
        raise AssertionError(f"{name} must be a string when present")
    return value


def _integer_argument(arguments: dict[str, object], name: str) -> int:
    """Return a required integer argument."""
    value = arguments[name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise AssertionError(f"{name} must be an integer")
    return value


def _bytes_argument(arguments: dict[str, object], name: str) -> bytes:
    """Return a required bytes argument."""
    value = arguments[name]
    if not isinstance(value, bytes):
        raise AssertionError(f"{name} must be bytes")
    return value


def _string_mapping_argument(arguments: dict[str, object], name: str) -> dict[str, str]:
    """Return one required string mapping argument."""
    return _string_mapping_value(arguments, name)


def _string_mapping_value(values: dict[str, object], name: str) -> dict[str, str]:
    """Return one required string mapping value."""
    raw = values[name]
    if not isinstance(raw, dict):
        raise AssertionError(f"{name} must be a mapping")
    raw_mapping = cast(dict[object, object], raw)
    result: dict[str, str] = {}
    for key, value in raw_mapping.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise AssertionError(f"{name} must contain string entries")
        result[key] = value
    return result


def _string_value(values: dict[str, object], name: str) -> str:
    """Return one required string mapping value."""
    value = values[name]
    if not isinstance(value, str):
        raise AssertionError(f"{name} must be a string")
    return value


def _optional_string_value(values: dict[str, object], name: str) -> str | None:
    """Return one optional string mapping value."""
    value = values[name]
    if value is not None and not isinstance(value, str):
        raise AssertionError(f"{name} must be a string when present")
    return value


def _parts(upload: dict[str, object]) -> dict[int, bytes]:
    """Return multipart part state."""
    value = upload["parts"]
    if not isinstance(value, dict):
        raise AssertionError("parts must be a mapping")
    raw_parts = cast(dict[object, object], value)
    for key, item in raw_parts.items():
        if not (
            isinstance(key, int)
            and not isinstance(key, bool)
            and isinstance(item, bytes)
        ):
            raise AssertionError("parts must contain integer byte entries")
    return cast(dict[int, bytes], value)


def _sha256(value: bytes) -> str:
    """Return a hexadecimal SHA-256 digest."""
    return hashlib.sha256(value).hexdigest()


@pytest.mark.asyncio
async def test_bounded_iteration_closes_response_after_early_exit() -> None:
    """A bounded iterator closes its body even when the consumer exits early."""
    client = _FakeS3Client()
    client.objects[("bucket", "source")] = _StoredObject(b"abcdef", {}, None)
    service = _service(client)

    async with service.iter_chunks(
        S3ObjectIdentity(bucket="bucket", key="source"),
        maximum_chunk_size=2,
    ) as chunks:
        assert await anext(chunks) == b"ab"

    body = client.bodies[0]
    assert body.closed is True
    assert body.read_sizes == [2]


@pytest.mark.asyncio
async def test_bounded_iteration_closes_for_non_cancelled_exit_paths() -> None:
    """Every iterator exit path closes the owned response body."""
    client = _FakeS3Client()
    identity = S3ObjectIdentity(bucket="bucket", key="source")
    client.objects[("bucket", "source")] = _StoredObject(b"abc", {}, None)
    service = _service(client)

    async with service.iter_chunks(identity, maximum_chunk_size=2) as chunks:
        assert [chunk async for chunk in chunks] == [b"ab", b"c"]
    assert client.bodies[-1].closed is True
    assert all(size == 2 for size in client.bodies[-1].read_sizes)

    with pytest.raises(RuntimeError, match="consumer failed"):
        async with service.iter_chunks(identity, maximum_chunk_size=2):
            raise RuntimeError("consumer failed")
    assert client.bodies[-1].closed is True

    failing_body = _FailingBody(b"abc")
    client.next_body = failing_body
    with pytest.raises(RuntimeError, match="read failed"):
        async with service.iter_chunks(identity, maximum_chunk_size=2) as chunks:
            await anext(chunks)
    assert failing_body.closed is True


@pytest.mark.asyncio
async def test_bounded_iteration_closes_when_reader_is_cancelled() -> None:
    """Task cancellation cannot retain an open S3 response body."""
    client = _FakeS3Client()
    identity = S3ObjectIdentity(bucket="bucket", key="source")
    client.objects[("bucket", "source")] = _StoredObject(b"abc", {}, None)
    blocking_body = _BlockingBody(b"abc")
    client.next_body = blocking_body
    service = _service(client)

    async def consume() -> None:
        async with service.iter_chunks(identity, maximum_chunk_size=2) as chunks:
            await anext(chunks)

    task = asyncio.create_task(consume())
    await blocking_body.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert blocking_body.closed is True


@pytest.mark.asyncio
async def test_head_propagates_unexpected_storage_error() -> None:
    """HEAD only converts actual not-found responses."""
    client = _FakeS3Client()
    client.head_error_code = "AccessDenied"
    service = _service(client)

    with pytest.raises(ClientError):
        await service.head(S3ObjectIdentity(bucket="bucket", key="source"))


@pytest.mark.asyncio
async def test_immutable_copy_replaces_untrusted_metadata_and_verifies_size() -> None:
    """Immutable copy only persists transfer-owned metadata on the destination."""
    body = b"source bytes"
    digest = _sha256(body)
    client = _FakeS3Client()
    client.objects[("bucket", "source")] = _StoredObject(
        body,
        {"untrusted": "discard"},
        "application/octet-stream",
    )
    service = _service(client)

    verified = await service.copy_immutable(
        source=S3ObjectIdentity(bucket="bucket", key="source"),
        destination=S3ObjectIdentity(bucket="bucket", key="transfer"),
        expected_size=len(body),
        transfer_metadata=S3TransferObjectMetadata(
            sha256=digest,
            content_type="application/octet-stream",
        ),
        multipart_copy_threshold=100,
        multipart_part_size=10,
    )

    assert verified.metadata.content_length == len(body)
    assert client.objects[("bucket", "transfer")].metadata == {
        "azents-transfer-sha256": digest
    }
    assert client.copy_requests[0]["MetadataDirective"] == "REPLACE"


@pytest.mark.asyncio
async def test_immutable_copy_rejects_destination_race_without_deleting_winner() -> (
    None
):
    """Conditional reservation preserves an already-created destination."""
    body = b"source bytes"
    client = _FakeS3Client()
    client.objects[("bucket", "source")] = _StoredObject(body, {}, None)
    winner = _StoredObject(b"winner", {"owner": "other"}, "text/plain")
    client.objects[("bucket", "transfer")] = winner
    service = _service(client)

    with pytest.raises(FileExistsError):
        await service.copy_immutable(
            source=S3ObjectIdentity(bucket="bucket", key="source"),
            destination=S3ObjectIdentity(bucket="bucket", key="transfer"),
            expected_size=len(body),
            transfer_metadata=S3TransferObjectMetadata(
                sha256=_sha256(body),
                content_type=None,
            ),
            multipart_copy_threshold=100,
            multipart_part_size=10,
        )

    assert client.objects[("bucket", "transfer")] == winner


@pytest.mark.asyncio
async def test_immutable_copy_fails_closed_when_source_changes_after_head() -> None:
    """A source ETag change prevents normal and multipart mixed-byte copies."""
    original = b"abcdefgh"
    mutated = b"abcdWXYZ"
    source = S3ObjectIdentity(bucket="bucket", key="source")

    normal_client = _FakeS3Client()
    normal_client.objects[("bucket", "source")] = _StoredObject(original, {}, None)
    normal_client.mutate_source_before_copy = mutated
    with pytest.raises(ClientError):
        await _service(normal_client).copy_immutable(
            source=source,
            destination=S3ObjectIdentity(bucket="bucket", key="normal"),
            expected_size=len(original),
            transfer_metadata=S3TransferObjectMetadata(
                sha256=_sha256(original),
                content_type=None,
            ),
            multipart_copy_threshold=100,
            multipart_part_size=4,
        )
    assert ("bucket", "normal") not in normal_client.objects

    multipart_client = _FakeS3Client()
    multipart_client.objects[("bucket", "source")] = _StoredObject(original, {}, None)
    multipart_client.mutate_source_before_part_copy = mutated
    with pytest.raises(ClientError):
        await _service(multipart_client).copy_immutable(
            source=source,
            destination=S3ObjectIdentity(bucket="bucket", key="multipart"),
            expected_size=len(original),
            transfer_metadata=S3TransferObjectMetadata(
                sha256=_sha256(original),
                content_type=None,
            ),
            multipart_copy_threshold=4,
            multipart_part_size=4,
        )
    assert ("bucket", "multipart") not in multipart_client.objects
    assert multipart_client.abort_calls == ["upload-1"]


@pytest.mark.asyncio
async def test_cancelled_small_copy_removes_its_reservation() -> None:
    """Cancelling a normal server-side copy leaves no reserved destination."""
    body = b"source bytes"
    client = _FakeS3Client()
    client.objects[("bucket", "source")] = _StoredObject(body, {}, None)
    client.block_copy = True
    service = _service(client)

    task = asyncio.create_task(
        service.copy_immutable(
            source=S3ObjectIdentity(bucket="bucket", key="source"),
            destination=S3ObjectIdentity(bucket="bucket", key="transfer"),
            expected_size=len(body),
            transfer_metadata=S3TransferObjectMetadata(
                sha256=_sha256(body),
                content_type=None,
            ),
            multipart_copy_threshold=100,
            multipart_part_size=10,
        )
    )
    await client.copy_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert ("bucket", "transfer") not in client.objects


@pytest.mark.asyncio
async def test_multipart_completion_returns_verified_object() -> None:
    """Multipart completion verifies exact size and persisted SHA-256 metadata."""
    body = b"firstsecond"
    digest = _sha256(body)
    client = _FakeS3Client()
    service = _service(client)
    upload = await service.create_multipart_upload(
        destination=S3ObjectIdentity(bucket="bucket", key="transfer"),
        transfer_metadata=S3TransferObjectMetadata(
            sha256=digest,
            content_type=None,
        ),
    )
    first = await service.upload_part(upload=upload, part_number=1, body=b"first")
    second = await service.upload_part(upload=upload, part_number=2, body=b"second")

    verified = await service.complete_multipart_upload(
        upload=upload,
        completed_parts=(first, second),
        expected_size=len(body),
        expected_sha256=digest,
    )

    assert verified.sha256 == digest
    assert client.objects[("bucket", "transfer")].body == body


@pytest.mark.asyncio
async def test_multipart_part_failure_aborts_upload() -> None:
    """A failed body part invalidates and aborts its multipart handle."""
    client = _FakeS3Client()
    service = _service(client)
    upload = await service.create_multipart_upload(
        destination=S3ObjectIdentity(bucket="bucket", key="transfer"),
        transfer_metadata=S3TransferObjectMetadata(
            sha256=_sha256(b"part"),
            content_type=None,
        ),
    )
    client.fail_upload_part_number = 1

    with pytest.raises(RuntimeError, match="part failed"):
        await service.upload_part(upload=upload, part_number=1, body=b"part")

    assert client.abort_calls == [upload.upload_id]
    assert upload.upload_id not in client.uploads


@pytest.mark.asyncio
async def test_failed_multipart_completion_aborts_and_removes_destination() -> None:
    """Failed multipart completion leaves no verified destination object."""
    client = _FakeS3Client()
    service = _service(client)
    upload = await service.create_multipart_upload(
        destination=S3ObjectIdentity(bucket="bucket", key="transfer"),
        transfer_metadata=S3TransferObjectMetadata(
            sha256=_sha256(b"part"),
            content_type=None,
        ),
    )
    part = await service.upload_part(upload=upload, part_number=1, body=b"part")
    client.fail_complete = True

    with pytest.raises(RuntimeError, match="complete failed"):
        await service.complete_multipart_upload(
            upload=upload,
            completed_parts=(part,),
            expected_size=4,
            expected_sha256=_sha256(b"part"),
        )

    assert client.abort_calls == [upload.upload_id]
    assert ("bucket", "transfer") not in client.objects


@pytest.mark.asyncio
async def test_ambiguous_multipart_completion_removes_owned_destination() -> None:
    """An ambiguous successful write is cleaned instead of returned as verified."""
    client = _FakeS3Client()
    service = _service(client)
    upload = await service.create_multipart_upload(
        destination=S3ObjectIdentity(bucket="bucket", key="transfer"),
        transfer_metadata=S3TransferObjectMetadata(
            sha256=_sha256(b"part"),
            content_type=None,
        ),
    )
    part = await service.upload_part(upload=upload, part_number=1, body=b"part")
    client.complete_then_raise = True

    with pytest.raises(RuntimeError, match="ambiguous completion"):
        await service.complete_multipart_upload(
            upload=upload,
            completed_parts=(part,),
            expected_size=4,
            expected_sha256=_sha256(b"part"),
        )

    assert ("bucket", "transfer") not in client.objects
    assert client.delete_calls == ["transfer"]


@pytest.mark.asyncio
async def test_cancelled_multipart_completion_aborts_without_destination() -> None:
    """Cancelling multipart finalization aborts the incomplete upload."""
    client = _FakeS3Client()
    service = _service(client)
    upload = await service.create_multipart_upload(
        destination=S3ObjectIdentity(bucket="bucket", key="transfer"),
        transfer_metadata=S3TransferObjectMetadata(
            sha256=_sha256(b"part"),
            content_type=None,
        ),
    )
    part = await service.upload_part(upload=upload, part_number=1, body=b"part")
    client.block_complete = True

    task = asyncio.create_task(
        service.complete_multipart_upload(
            upload=upload,
            completed_parts=(part,),
            expected_size=4,
            expected_sha256=_sha256(b"part"),
        )
    )
    await client.complete_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert client.abort_calls == [upload.upload_id]
    assert ("bucket", "transfer") not in client.objects


@pytest.mark.asyncio
async def test_multipart_completion_race_preserves_existing_destination() -> None:
    """A conditional completion loser never deletes the winning object."""
    client = _FakeS3Client()
    service = _service(client)
    upload = await service.create_multipart_upload(
        destination=S3ObjectIdentity(bucket="bucket", key="transfer"),
        transfer_metadata=S3TransferObjectMetadata(
            sha256=_sha256(b"part"),
            content_type=None,
        ),
    )
    part = await service.upload_part(upload=upload, part_number=1, body=b"part")
    winner = _StoredObject(b"winner", {"owner": "other"}, None)
    client.objects[("bucket", "transfer")] = winner

    with pytest.raises(FileExistsError):
        await service.complete_multipart_upload(
            upload=upload,
            completed_parts=(part,),
            expected_size=4,
            expected_sha256=_sha256(b"part"),
        )

    assert client.objects[("bucket", "transfer")] == winner
    assert client.abort_calls == [upload.upload_id]


@pytest.mark.asyncio
async def test_zero_byte_creation_and_bounded_prefix_cleanup() -> None:
    """Zero-byte writes verify normally and cleanup retains per-key failures."""
    empty_digest = _sha256(b"")
    client = _FakeS3Client()
    service = _service(client)
    await service.create_empty_immutable(
        destination=S3ObjectIdentity(bucket="bucket", key="prefix/empty"),
        transfer_metadata=S3TransferObjectMetadata(
            sha256=empty_digest,
            content_type="text/plain",
        ),
    )
    client.objects[("bucket", "prefix/second")] = _StoredObject(b"2", {}, None)
    client.objects[("bucket", "prefix/third")] = _StoredObject(b"3", {}, None)
    client.failed_delete_keys.add("prefix/second")

    first_page = await service.delete_prefix_bounded(
        bucket="bucket", prefix="prefix/", page_size=2
    )
    second_page = await service.delete_prefix_bounded(
        bucket="bucket",
        prefix="prefix/",
        page_size=2,
        continuation_token=first_page.next_continuation_token,
    )

    assert {item.key for item in first_page.deleted + second_page.deleted} == {
        "prefix/empty",
        "prefix/third",
    }
    assert {item.key for item in first_page.failed + second_page.failed} == {
        "prefix/second"
    }
    assert client.list_calls == [None, "2"]


@pytest.mark.asyncio
async def test_zero_byte_destination_race_preserves_existing_object() -> None:
    """Conditional empty creation cannot overwrite or delete another object."""
    client = _FakeS3Client()
    winner = _StoredObject(b"winner", {"owner": "other"}, None)
    client.objects[("bucket", "empty")] = winner
    service = _service(client)

    with pytest.raises(FileExistsError):
        await service.create_empty_immutable(
            destination=S3ObjectIdentity(bucket="bucket", key="empty"),
            transfer_metadata=S3TransferObjectMetadata(
                sha256=_sha256(b""),
                content_type=None,
            ),
        )

    assert client.objects[("bucket", "empty")] == winner


@pytest.mark.asyncio
async def test_zero_byte_creation_rejects_non_empty_digest() -> None:
    """Zero-byte verification cannot persist an arbitrary digest."""
    service = _service(_FakeS3Client())

    with pytest.raises(ValueError, match="empty content"):
        await service.create_empty_immutable(
            destination=S3ObjectIdentity(bucket="bucket", key="empty"),
            transfer_metadata=S3TransferObjectMetadata(
                sha256="0" * 64,
                content_type=None,
            ),
        )


@pytest.mark.asyncio
async def test_verification_rejects_size_sha_and_backend_checksum_mismatch() -> None:
    """Every available integrity signal must match the trusted manifest."""
    body = b"body"
    digest = _sha256(body)
    identity = S3ObjectIdentity(bucket="bucket", key="transfer")
    client = _FakeS3Client()
    service = _service(client)

    client.objects[("bucket", "transfer")] = _StoredObject(
        body,
        {"azents-transfer-sha256": digest},
        None,
    )
    with pytest.raises(ValueError, match="size"):
        await service.verify_transfer_object(
            identity=identity,
            expected_size=len(body) + 1,
            expected_sha256=digest,
        )

    client.objects[("bucket", "transfer")] = _StoredObject(
        body,
        {"azents-transfer-sha256": "0" * 64},
        None,
    )
    with pytest.raises(ValueError, match="metadata"):
        await service.verify_transfer_object(
            identity=identity,
            expected_size=len(body),
            expected_sha256=digest,
        )

    client.objects[("bucket", "transfer")] = _StoredObject(
        body,
        {"azents-transfer-sha256": digest},
        None,
        checksum_sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="checksum"):
        await service.verify_transfer_object(
            identity=identity,
            expected_size=len(body),
            expected_sha256=digest,
        )


@pytest.mark.asyncio
async def test_abort_is_idempotent() -> None:
    """Repeated abort calls leave no upload and do not fail."""
    client = _FakeS3Client()
    service = _service(client)
    upload = await service.create_multipart_upload(
        destination=S3ObjectIdentity(bucket="bucket", key="transfer"),
        transfer_metadata=S3TransferObjectMetadata(
            sha256=_sha256(b"part"),
            content_type=None,
        ),
    )

    await service.abort_multipart_upload(upload=upload)
    await service.abort_multipart_upload(upload=upload)

    assert client.abort_calls == [upload.upload_id, upload.upload_id]


@pytest.mark.asyncio
async def test_multipart_manifest_rejects_gaps() -> None:
    """Multipart completion refuses non-consecutive part evidence."""
    client = _FakeS3Client()
    service = _service(client)
    with pytest.raises(ValueError, match="ordered consecutive"):
        await service.complete_multipart_upload(
            upload=S3MultipartUpload(
                identity=S3ObjectIdentity(bucket="bucket", key="transfer"),
                upload_id="upload-1",
            ),
            completed_parts=(
                S3CompletedPart(part_number=1, etag="one"),
                S3CompletedPart(part_number=3, etag="three"),
            ),
            expected_size=2,
            expected_sha256=_sha256(b"ok"),
        )
