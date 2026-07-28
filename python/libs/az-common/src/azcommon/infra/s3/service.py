"""S3-compatible object storage operations."""

import base64
import datetime
import hashlib
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import IO, Any, cast

from botocore.exceptions import ClientError as BotoClientError
from types_aiobotocore_s3.client import S3Client

_TRANSFER_SHA256_METADATA_KEY = "azents-transfer-sha256"


@dataclass(frozen=True)
class S3ObjectIdentity:
    """An S3 object location owned by a trusted process."""

    bucket: str
    key: str


@dataclass(frozen=True)
class S3ObjectMetadata:
    """Metadata returned by an S3 HEAD operation without reading object bytes."""

    identity: S3ObjectIdentity
    content_length: int
    content_type: str | None
    etag: str | None
    checksum_sha256: str | None
    user_metadata: Mapping[str, str]
    last_modified_at: datetime.datetime | None


@dataclass(frozen=True)
class S3VerifiedObject:
    """Verified immutable transfer-object metadata."""

    metadata: S3ObjectMetadata
    sha256: str


@dataclass(frozen=True)
class S3TransferObjectMetadata:
    """Allowlisted metadata persisted on an immutable transfer object."""

    sha256: str
    content_type: str | None

    def __post_init__(self) -> None:
        _validate_sha256(self.sha256)


@dataclass(frozen=True)
class S3MultipartUpload:
    """Opaque multipart-upload identity for a trusted process."""

    identity: S3ObjectIdentity
    upload_id: str


@dataclass(frozen=True)
class S3CompletedPart:
    """One ordered, completed multipart upload part."""

    part_number: int
    etag: str


@dataclass(frozen=True)
class S3ObjectPage:
    """One bounded page of object identities."""

    objects: tuple[S3ObjectIdentity, ...]
    next_continuation_token: str | None


@dataclass(frozen=True)
class S3DeleteResult:
    """Bounded deletion evidence including retryable failures."""

    deleted: tuple[S3ObjectIdentity, ...]
    failed: tuple[S3ObjectIdentity, ...]
    next_continuation_token: str | None


class S3Service:
    """S3-compatible object-storage service."""

    def __init__(
        self, s3_client: S3Client, public_s3_client: S3Client | None = None
    ) -> None:
        """Initialize the service.

        :param s3_client: Client used for trusted internal operations.
        :param public_s3_client: Client used to issue public presigned URLs. When
            omitted, uses ``s3_client``.
        """
        self.s3_client: Any = s3_client
        self.public_s3_client: Any = public_s3_client or s3_client

    async def upload(
        self,
        bucket: str,
        key: str,
        body: str | bytes | IO[str] | IO[bytes],
        *,
        content_type: str | None = None,
    ) -> None:
        """Upload one complete bounded object.

        :param bucket: Destination bucket.
        :param key: Destination key.
        :param body: Object body.
        :param content_type: Optional MIME type.
        """
        args: dict[str, Any] = {
            "Bucket": bucket,
            "Key": key,
            "Body": body,
        }
        if content_type:
            args["ContentType"] = content_type
        await self.s3_client.put_object(**args)

    async def download_bytes(self, bucket: str, key: str) -> bytes | None:
        """Download one complete bounded object.

        :param bucket: Source bucket.
        :param key: Source key.
        :returns: Object bytes, or ``None`` when the object does not exist.
        """
        try:
            response = await self.s3_client.get_object(Bucket=bucket, Key=key)
        except BotoClientError as exc:
            if _is_not_found_error(exc):
                return None
            raise
        body = response["Body"]
        try:
            content = await body.read()
            return bytes(content)
        finally:
            body.close()

    async def head(self, identity: S3ObjectIdentity) -> S3ObjectMetadata | None:
        """Read object metadata without downloading its body.

        :param identity: Object to inspect.
        :returns: Metadata, or ``None`` when the object does not exist.
        """
        try:
            response = await self.s3_client.head_object(
                Bucket=identity.bucket,
                Key=identity.key,
            )
        except BotoClientError as exc:
            if _is_not_found_error(exc):
                return None
            raise
        return _metadata_from_response(identity=identity, response=response)

    @asynccontextmanager
    async def iter_chunks(
        self,
        identity: S3ObjectIdentity,
        *,
        maximum_chunk_size: int,
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        """Open a bounded object-body iterator.

        The context manager owns the response body and closes it when iteration ends,
        the caller exits early, an exception occurs, or the task is cancelled.

        :param identity: Object to stream.
        :param maximum_chunk_size: Maximum byte count returned in each chunk.
        :raises ValueError: If ``maximum_chunk_size`` is not positive.
        :raises FileNotFoundError: If the object does not exist.
        :returns: An async iterator of ordered byte chunks.
        """
        if maximum_chunk_size <= 0:
            raise ValueError("maximum_chunk_size must be positive")
        try:
            response = await self.s3_client.get_object(
                Bucket=identity.bucket,
                Key=identity.key,
            )
        except BotoClientError as exc:
            if _is_not_found_error(exc):
                raise FileNotFoundError(identity.key) from exc
            raise
        body = response["Body"]

        async def chunks() -> AsyncIterator[bytes]:
            """Yield bounded chunks from the open response body."""
            while True:
                chunk = await body.read(maximum_chunk_size)
                if not chunk:
                    return
                yield bytes(chunk)

        try:
            yield chunks()
        finally:
            body.close()

    async def copy_immutable(
        self,
        *,
        source: S3ObjectIdentity,
        destination: S3ObjectIdentity,
        expected_size: int,
        transfer_metadata: S3TransferObjectMetadata,
        multipart_copy_threshold: int,
        multipart_part_size: int,
    ) -> S3VerifiedObject:
        """Copy a trusted source into a new immutable transfer object.

        :param source: Existing authorized source object.
        :param destination: New transfer-object destination.
        :param expected_size: Trusted source byte count.
        :param transfer_metadata: Allowlisted metadata for the destination.
        :param multipart_copy_threshold: Maximum size for one server-side copy.
        :param multipart_part_size: Byte count for each multipart-copy range.
        :raises FileExistsError: If the destination already exists.
        :raises FileNotFoundError: If the source does not exist.
        :returns: Verified destination metadata.
        """
        if expected_size < 0:
            raise ValueError("expected_size must not be negative")
        if multipart_copy_threshold <= 0:
            raise ValueError("multipart_copy_threshold must be positive")
        if multipart_part_size <= 0:
            raise ValueError("multipart_part_size must be positive")
        source_metadata = await self.head(source)
        if source_metadata is None:
            raise FileNotFoundError(source.key)
        if source_metadata.content_length != expected_size:
            raise ValueError("source size does not match expected_size")
        if source_metadata.etag is None:
            raise ValueError("source copy requires stable ETag evidence")
        if expected_size == 0:
            return await self.create_empty_immutable(
                destination=destination,
                transfer_metadata=transfer_metadata,
            )
        return await self._multipart_copy(
            source=source,
            destination=destination,
            expected_size=expected_size,
            transfer_metadata=transfer_metadata,
            multipart_part_size=(
                expected_size
                if expected_size <= multipart_copy_threshold
                else multipart_part_size
            ),
            source_etag=source_metadata.etag,
        )

    async def create_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3MultipartUpload:
        """Create a new immutable multipart upload.

        :param destination: New transfer-object destination.
        :param transfer_metadata: Allowlisted metadata for the destination.
        :raises FileExistsError: If the destination already exists.
        :returns: Opaque upload handle.
        """
        await self._ensure_destination_absent(destination)
        response = await self.s3_client.create_multipart_upload(
            Bucket=destination.bucket,
            Key=destination.key,
            Metadata={_TRANSFER_SHA256_METADATA_KEY: transfer_metadata.sha256},
            **_content_type_args(transfer_metadata.content_type),
        )
        upload_id = response.get("UploadId")
        if not isinstance(upload_id, str) or not upload_id:
            raise RuntimeError("S3 did not return a multipart upload ID")
        return S3MultipartUpload(identity=destination, upload_id=upload_id)

    async def upload_part(
        self,
        *,
        upload: S3MultipartUpload,
        part_number: int,
        body: bytes,
    ) -> S3CompletedPart:
        """Upload one multipart body part.

        :param upload: Trusted multipart upload handle.
        :param part_number: One-based ordered part number.
        :param body: Bounded part bytes.
        :returns: Completion evidence for the uploaded part.
        """
        if part_number <= 0:
            raise ValueError("part_number must be positive")
        if not body:
            raise ValueError("multipart parts must not be empty")
        try:
            response = await self.s3_client.upload_part(
                Bucket=upload.identity.bucket,
                Key=upload.identity.key,
                UploadId=upload.upload_id,
                PartNumber=part_number,
                Body=body,
            )
            etag = response.get("ETag")
            if not isinstance(etag, str) or not etag:
                raise RuntimeError("S3 did not return a multipart part ETag")
            return S3CompletedPart(part_number=part_number, etag=etag)
        except BaseException:
            await self.abort_multipart_upload(upload=upload)
            raise

    async def complete_multipart_upload(
        self,
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        """Complete and verify a multipart upload.

        :param upload: Trusted multipart upload handle.
        :param completed_parts: Ordered completion evidence.
        :param expected_size: Exact completed object size.
        :param expected_sha256: Required transfer-owned SHA-256 value.
        :returns: Verified completed-object metadata.
        """
        try:
            if expected_size <= 0:
                raise ValueError(
                    "multipart completion requires a positive expected_size"
                )
            _validate_sha256(expected_sha256)
            _validate_completed_parts(completed_parts)
            await self.s3_client.complete_multipart_upload(
                Bucket=upload.identity.bucket,
                Key=upload.identity.key,
                UploadId=upload.upload_id,
                MultipartUpload={
                    "Parts": [
                        {"PartNumber": part.part_number, "ETag": part.etag}
                        for part in completed_parts
                    ]
                },
                IfNoneMatch="*",
            )
            return await self.verify_transfer_object(
                identity=upload.identity,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )
        except BotoClientError as exc:
            await self.abort_multipart_upload(upload=upload)
            if _is_precondition_failed_error(exc):
                raise FileExistsError(upload.identity.key) from exc
            await self._delete_owned_destination(
                upload.identity,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )
            raise
        except BaseException:
            await self.abort_multipart_upload(upload=upload)
            await self._delete_owned_destination(
                upload.identity,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )
            raise

    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None:
        """Abort a multipart upload idempotently.

        :param upload: Trusted multipart upload handle.
        """
        try:
            await self.s3_client.abort_multipart_upload(
                Bucket=upload.identity.bucket,
                Key=upload.identity.key,
                UploadId=upload.upload_id,
            )
        except BotoClientError as exc:
            if _is_not_found_error(exc) or _is_no_such_upload_error(exc):
                return
            raise

    async def create_empty_immutable(
        self,
        *,
        destination: S3ObjectIdentity,
        transfer_metadata: S3TransferObjectMetadata,
    ) -> S3VerifiedObject:
        """Create and verify a zero-byte immutable transfer object.

        :param destination: New transfer-object destination.
        :param transfer_metadata: Allowlisted metadata for the destination.
        :returns: Verified zero-byte metadata.
        """
        empty_sha256 = hashlib.sha256(b"").hexdigest()
        if transfer_metadata.sha256 != empty_sha256:
            raise ValueError("zero-byte object requires the SHA-256 of empty content")
        try:
            await self.s3_client.put_object(
                Bucket=destination.bucket,
                Key=destination.key,
                Body=b"",
                Metadata={_TRANSFER_SHA256_METADATA_KEY: transfer_metadata.sha256},
                IfNoneMatch="*",
                **_content_type_args(transfer_metadata.content_type),
            )
            return await self.verify_transfer_object(
                identity=destination,
                expected_size=0,
                expected_sha256=transfer_metadata.sha256,
            )
        except BotoClientError as exc:
            if _is_precondition_failed_error(exc):
                raise FileExistsError(destination.key) from exc
            await self._delete_owned_destination(
                destination,
                expected_size=0,
                expected_sha256=transfer_metadata.sha256,
            )
            raise
        except BaseException:
            await self._delete_owned_destination(
                destination,
                expected_size=0,
                expected_sha256=transfer_metadata.sha256,
            )
            raise

    async def verify_transfer_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        """Verify exact persisted size and transfer-owned SHA-256 metadata.

        :param identity: Completed transfer object.
        :param expected_size: Exact expected byte count.
        :param expected_sha256: Required SHA-256 digest in hexadecimal form.
        :raises FileNotFoundError: If the object does not exist.
        :raises ValueError: If object metadata does not match the trusted manifest.
        :returns: Verified object metadata.
        """
        metadata = await self.head(identity)
        if metadata is None:
            raise FileNotFoundError(identity.key)
        if metadata.content_length != expected_size:
            raise ValueError("object size does not match expected_size")
        persisted_sha256 = metadata.user_metadata.get(_TRANSFER_SHA256_METADATA_KEY)
        if persisted_sha256 != expected_sha256:
            raise ValueError("object SHA-256 metadata does not match expected_sha256")
        if metadata.checksum_sha256 is not None and not _checksum_matches(
            metadata.checksum_sha256,
            expected_sha256,
        ):
            raise ValueError("object checksum does not match expected_sha256")
        return S3VerifiedObject(metadata=metadata, sha256=expected_sha256)

    async def list_page(
        self,
        *,
        bucket: str,
        prefix: str,
        maximum_keys: int,
        continuation_token: str | None,
    ) -> S3ObjectPage:
        """Return one bounded page of object identities.

        :param bucket: Bucket to inspect.
        :param prefix: Object-key prefix.
        :param maximum_keys: Maximum objects in the page.
        :param continuation_token: Token returned by a preceding page.
        :returns: One page and its optional next token.
        """
        if maximum_keys <= 0:
            raise ValueError("maximum_keys must be positive")
        args: dict[str, Any] = {
            "Bucket": bucket,
            "Prefix": prefix,
            "MaxKeys": maximum_keys,
        }
        if continuation_token is not None:
            args["ContinuationToken"] = continuation_token
        response = await self.s3_client.list_objects_v2(**args)
        contents = response.get("Contents", [])
        objects = tuple(
            S3ObjectIdentity(bucket=bucket, key=key)
            for object_summary in contents
            if isinstance((key := object_summary.get("Key")), str)
        )
        next_token = response.get("NextContinuationToken")
        return S3ObjectPage(
            objects=objects,
            next_continuation_token=next_token if isinstance(next_token, str) else None,
        )

    async def delete_prefix_bounded(
        self,
        *,
        bucket: str,
        prefix: str,
        page_size: int,
        continuation_token: str | None = None,
    ) -> S3DeleteResult:
        """Delete a prefix through bounded pages and retain per-key failures.

        :param bucket: Bucket containing the keys.
        :param prefix: Key prefix to delete.
        :param page_size: Maximum keys read and deleted per request.
        :param continuation_token: Token returned by the preceding bounded page.
        :returns: One bounded deletion page and continuation evidence.
        """
        if page_size <= 0 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        page = await self.list_page(
            bucket=bucket,
            prefix=prefix,
            maximum_keys=page_size,
            continuation_token=continuation_token,
        )
        deleted: list[S3ObjectIdentity] = []
        failed: list[S3ObjectIdentity] = []
        if page.objects:
            response = await self.s3_client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": item.key} for item in page.objects]},
            )
            deleted_keys = {
                item["Key"]
                for item in response.get("Deleted", [])
                if isinstance(item.get("Key"), str)
            }
            failed_keys = {
                item["Key"]
                for item in response.get("Errors", [])
                if isinstance(item.get("Key"), str)
            }
            for item in page.objects:
                if item.key in deleted_keys:
                    deleted.append(item)
                elif item.key in failed_keys or item.key not in deleted_keys:
                    failed.append(item)
        return S3DeleteResult(
            deleted=tuple(deleted),
            failed=tuple(failed),
            next_continuation_token=page.next_continuation_token,
        )

    async def copy(
        self,
        destination_bucket: str,
        destination_key: str,
        source_bucket: str,
        source_key: str,
    ) -> None:
        """Copy one object using the existing unrestricted API.

        :param destination_bucket: Destination bucket.
        :param destination_key: Destination key.
        :param source_bucket: Source bucket.
        :param source_key: Source key.
        """
        await self.s3_client.copy_object(
            Bucket=destination_bucket,
            Key=destination_key,
            CopySource={"Bucket": source_bucket, "Key": source_key},
        )

    async def delete(self, bucket: str, key: str) -> None:
        """Delete one object.

        :param bucket: Object bucket.
        :param key: Object key.
        """
        await self.s3_client.delete_object(Bucket=bucket, Key=key)

    async def move(
        self,
        destination_bucket: str,
        destination_key: str,
        source_bucket: str,
        source_key: str,
    ) -> None:
        """Move one object using the existing unrestricted API.

        :param destination_bucket: Destination bucket.
        :param destination_key: Destination key.
        :param source_bucket: Source bucket.
        :param source_key: Source key.
        """
        await self.copy(
            destination_bucket=destination_bucket,
            destination_key=destination_key,
            source_bucket=source_bucket,
            source_key=source_key,
        )
        await self.delete(bucket=source_bucket, key=source_key)

    async def get_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: datetime.timedelta,
    ) -> str:
        """Create a presigned GET URL.

        :param bucket: Object bucket.
        :param key: Object key.
        :param expires_in: URL lifetime.
        :returns: Presigned download URL.
        """
        return await self.public_s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": bucket,
                "Key": key,
            },
            ExpiresIn=int(expires_in.total_seconds()),
        )

    async def get_upload_url(
        self,
        bucket: str,
        key: str,
        content_type: str,
        expires_in: datetime.timedelta,
    ) -> str:
        """Create a presigned PUT URL.

        :param bucket: Object bucket.
        :param key: Object key.
        :param content_type: Required MIME type.
        :param expires_in: URL lifetime.
        :returns: Presigned upload URL.
        """
        return await self.public_s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=int(expires_in.total_seconds()),
        )

    async def exists(self, bucket: str, key: str) -> bool:
        """Return whether an object exists.

        :param bucket: Object bucket.
        :param key: Object key.
        :returns: Whether the object exists.
        """
        return await self.head(S3ObjectIdentity(bucket=bucket, key=key)) is not None

    async def list_keys(self, bucket: str, prefix: str) -> list[str]:
        """List every key using the existing eager API.

        :param bucket: Bucket to inspect.
        :param prefix: Key prefix.
        :returns: All matching keys.
        """
        keys: list[str] = []
        paginator = self.s3_client.get_paginator("list_objects_v2")
        async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj.get("Key")
                if key is not None:
                    keys.append(key)
        return keys

    async def delete_by_prefix(self, bucket: str, prefix: str) -> int:
        """Delete every key using the existing eager API.

        :param bucket: Bucket containing the keys.
        :param prefix: Key prefix.
        :returns: Number of attempted deletions.
        """
        keys = await self.list_keys(bucket, prefix)
        if not keys:
            return 0
        deleted_count = 0
        for index in range(0, len(keys), 1000):
            batch = keys[index : index + 1000]
            await self.s3_client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": key} for key in batch]},
            )
            deleted_count += len(batch)
        return deleted_count

    async def _ensure_destination_absent(self, destination: S3ObjectIdentity) -> None:
        """Reject reuse of an immutable transfer-object destination."""
        if await self.head(destination) is not None:
            raise FileExistsError(destination.key)

    async def _multipart_copy(
        self,
        *,
        source: S3ObjectIdentity,
        destination: S3ObjectIdentity,
        expected_size: int,
        transfer_metadata: S3TransferObjectMetadata,
        multipart_part_size: int,
        source_etag: str,
    ) -> S3VerifiedObject:
        """Copy one source through bounded server-side multipart ranges."""
        upload = await self.create_multipart_upload(
            destination=destination,
            transfer_metadata=transfer_metadata,
        )
        completed_parts: list[S3CompletedPart] = []
        try:
            for part_number, offset in enumerate(
                range(0, expected_size, multipart_part_size),
                start=1,
            ):
                response = await self.s3_client.upload_part_copy(
                    Bucket=destination.bucket,
                    Key=destination.key,
                    UploadId=upload.upload_id,
                    PartNumber=part_number,
                    CopySource={"Bucket": source.bucket, "Key": source.key},
                    CopySourceRange=(
                        f"bytes={offset}-"
                        f"{min(offset + multipart_part_size, expected_size) - 1}"
                    ),
                    CopySourceIfMatch=source_etag,
                )
                copy_part_result = response.get("CopyPartResult", {})
                etag = copy_part_result.get("ETag")
                if not isinstance(etag, str) or not etag:
                    raise RuntimeError("S3 did not return a multipart copy ETag")
                completed_parts.append(
                    S3CompletedPart(part_number=part_number, etag=etag)
                )
        except BaseException:
            await self.abort_multipart_upload(upload=upload)
            raise
        return await self.complete_multipart_upload(
            upload=upload,
            completed_parts=tuple(completed_parts),
            expected_size=expected_size,
            expected_sha256=transfer_metadata.sha256,
        )

    async def _delete_owned_destination(
        self,
        destination: S3ObjectIdentity,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        """Delete completed-object evidence only under its observed ETag."""
        metadata = await self.head(destination)
        if metadata is None:
            return
        completed = (
            metadata.content_length == expected_size
            and metadata.user_metadata.get(_TRANSFER_SHA256_METADATA_KEY)
            == expected_sha256
        )
        if not completed:
            return
        if metadata.etag is None:
            raise RuntimeError(
                "owned destination cleanup requires stable ETag evidence"
            )
        try:
            await self.s3_client.delete_object(
                Bucket=destination.bucket,
                Key=destination.key,
                IfMatch=metadata.etag,
            )
        except BotoClientError as exc:
            if _is_not_found_error(exc):
                return
            raise


def _metadata_from_response(
    *,
    identity: S3ObjectIdentity,
    response: Mapping[str, Any],
) -> S3ObjectMetadata:
    """Convert one S3 metadata response into a frozen library value."""
    content_length = response.get("ContentLength")
    if not isinstance(content_length, int) or isinstance(content_length, bool):
        raise RuntimeError("S3 HEAD response did not contain ContentLength")
    content_type = response.get("ContentType")
    etag = response.get("ETag")
    checksum_sha256 = response.get("ChecksumSHA256")
    last_modified_at = response.get("LastModified")
    raw_metadata: object = response.get("Metadata", {})
    if not isinstance(raw_metadata, dict):
        raise RuntimeError("S3 HEAD response metadata was not a mapping")
    metadata = cast(dict[str, object], raw_metadata)
    user_metadata = MappingProxyType(
        {key: value for key, value in metadata.items() if isinstance(value, str)}
    )
    return S3ObjectMetadata(
        identity=identity,
        content_length=content_length,
        content_type=content_type if isinstance(content_type, str) else None,
        etag=etag if isinstance(etag, str) else None,
        checksum_sha256=(checksum_sha256 if isinstance(checksum_sha256, str) else None),
        user_metadata=user_metadata,
        last_modified_at=(
            last_modified_at
            if isinstance(last_modified_at, datetime.datetime)
            else None
        ),
    )


def _content_type_args(content_type: str | None) -> dict[str, str]:
    """Return optional S3 content-type request arguments."""
    if content_type is None:
        return {}
    return {"ContentType": content_type}


def _validate_completed_parts(completed_parts: tuple[S3CompletedPart, ...]) -> None:
    """Require a non-empty consecutive ordered multipart manifest."""
    if not completed_parts:
        raise ValueError("completed_parts must not be empty")
    expected_numbers = range(1, len(completed_parts) + 1)
    if [part.part_number for part in completed_parts] != list(expected_numbers):
        raise ValueError("completed_parts must be ordered consecutive part numbers")


def _validate_sha256(value: str) -> None:
    """Require one lowercase hexadecimal SHA-256 digest."""
    if (
        len(value) != 64
        or value.lower() != value
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("SHA-256 must be lowercase hexadecimal")


def _checksum_matches(persisted_checksum: str, expected_sha256: str) -> bool:
    """Compare hexadecimal or base64 S3 checksum evidence to a SHA-256 digest."""
    if persisted_checksum == expected_sha256:
        return True
    try:
        decoded = base64.b64decode(persisted_checksum, validate=True)
    except ValueError:
        return False
    return decoded.hex() == expected_sha256


def _is_not_found_error(exc: BotoClientError) -> bool:
    """Return whether a client error represents an absent object."""
    code = exc.response.get("Error", {}).get("Code")
    return code in {"NoSuchKey", "NoSuchUpload", "404", "NotFound"}


def _is_no_such_upload_error(exc: BotoClientError) -> bool:
    """Return whether a client error represents an absent multipart upload."""
    return exc.response.get("Error", {}).get("Code") == "NoSuchUpload"


def _is_precondition_failed_error(exc: BotoClientError) -> bool:
    """Return whether an S3 conditional write rejected an existing destination."""
    return exc.response.get("Error", {}).get("Code") in {
        "PreconditionFailed",
        "412",
        "ConditionalRequestConflict",
        "409",
    }
