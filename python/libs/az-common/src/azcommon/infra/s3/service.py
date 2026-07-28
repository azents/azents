"""S3-compatible object storage operations."""

import asyncio
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
_PRODUCT_PUBLICATION_SHA256_METADATA_KEY = "azents-product-publication-sha256"
_PRODUCT_PUBLICATION_ID_METADATA_KEY = "azents-product-publication-id"


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
class S3ProductPublicationMetadata:
    """Exact ownership evidence for one uncommitted product-object publication."""

    sha256: str
    content_type: str | None
    publication_id: str

    def __post_init__(self) -> None:
        _validate_sha256(self.sha256)
        if not self.publication_id:
            raise ValueError("publication_id must not be empty")


@dataclass(frozen=True)
class S3ProductPublicationResult:
    """Verified product publication with exact creation evidence."""

    metadata: S3ObjectMetadata
    created: bool


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
class S3ListedObject:
    """One listed object with storage-owned age evidence."""

    identity: S3ObjectIdentity
    last_modified_at: datetime.datetime


@dataclass(frozen=True)
class S3ObjectSummaryPage:
    """One bounded page of object identities and modification times."""

    objects: tuple[S3ListedObject, ...]
    next_continuation_token: str | None
    skipped_entries: int


@dataclass(frozen=True)
class S3ListedMultipartUpload:
    """One listed incomplete multipart upload with initiation time."""

    upload: S3MultipartUpload
    initiated_at: datetime.datetime


@dataclass(frozen=True)
class S3MultipartUploadPage:
    """One bounded page of incomplete multipart uploads."""

    uploads: tuple[S3ListedMultipartUpload, ...]
    next_key_marker: str | None
    next_upload_id_marker: str | None
    skipped_entries: int


@dataclass(frozen=True)
class S3DeleteResult:
    """Bounded deletion evidence including retryable failures."""

    deleted: tuple[S3ObjectIdentity, ...]
    failed: tuple[S3ObjectIdentity, ...]
    next_continuation_token: str | None


class S3TransferCleanupRequired(RuntimeError):
    """Raised when an attempted immutable write needs durable cleanup retry."""

    def __init__(
        self,
        message: str,
        *,
        multipart_cleanup_required: bool,
        completed_object_cleanup_required: bool,
    ) -> None:
        if not multipart_cleanup_required and not completed_object_cleanup_required:
            raise ValueError("At least one transfer cleanup artifact is required")
        super().__init__(message)
        self.multipart_cleanup_required = multipart_cleanup_required
        self.completed_object_cleanup_required = completed_object_cleanup_required


class S3TransferCancelled(asyncio.CancelledError):
    """Cancellation that retains exact durable-cleanup responsibility."""

    def __init__(
        self,
        *,
        multipart_cleanup_required: bool,
        completed_object_cleanup_required: bool,
    ) -> None:
        if not multipart_cleanup_required and not completed_object_cleanup_required:
            raise ValueError("At least one transfer cleanup artifact is required")
        super().__init__("S3 transfer cancelled with cleanup responsibility")
        self.multipart_cleanup_required = multipart_cleanup_required
        self.completed_object_cleanup_required = completed_object_cleanup_required


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

    async def copy_verified_transfer_object_to_product(
        self,
        *,
        source: S3ObjectIdentity,
        destination: S3ObjectIdentity,
        expected_size: int,
        publication_metadata: S3ProductPublicationMetadata,
    ) -> S3ProductPublicationResult:
        """Native-copy a verified transfer object to one product-object key.

        :param source: Verified transfer-object source.
        :param destination: Preallocated immutable product-object destination.
        :param expected_size: Exact verified transfer byte count.
        :param publication_metadata: Product content and cleanup ownership evidence.
        :raises ValueError: If an existing final object does not match exactly.
        :returns: Verified final object and whether this invocation created it.
        """
        source_verified = await self.verify_transfer_object(
            identity=source,
            expected_size=expected_size,
            expected_sha256=publication_metadata.sha256,
        )
        source_etag = source_verified.metadata.etag
        if source_etag is None:
            raise ValueError("source copy requires stable ETag evidence")
        try:
            await self.s3_client.copy_object(
                Bucket=destination.bucket,
                Key=destination.key,
                CopySource={"Bucket": source.bucket, "Key": source.key},
                CopySourceIfMatch=source_etag,
                IfNoneMatch="*",
                MetadataDirective="REPLACE",
                Metadata=_product_publication_user_metadata(publication_metadata),
                **_content_type_args(publication_metadata.content_type),
            )
            return S3ProductPublicationResult(
                metadata=await self.verify_product_publication_object(
                    identity=destination,
                    expected_size=expected_size,
                    publication_metadata=publication_metadata,
                ),
                created=True,
            )
        except asyncio.CancelledError:
            raise
        except BotoClientError as exc:
            if _is_precondition_failed_error(exc):
                try:
                    return S3ProductPublicationResult(
                        metadata=await self.verify_product_publication_object(
                            identity=destination,
                            expected_size=expected_size,
                            publication_metadata=publication_metadata,
                        ),
                        created=False,
                    )
                except FileNotFoundError:
                    pass
            raise

    async def verify_product_publication_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        publication_metadata: S3ProductPublicationMetadata,
    ) -> S3ObjectMetadata:
        """Verify one final product object without downloading its bytes.

        :param identity: Final product-object destination.
        :param expected_size: Exact verified transfer byte count.
        :param publication_metadata: Exact expected product metadata.
        :raises FileNotFoundError: If the object does not exist.
        :returns: Verified final product-object metadata.
        """
        metadata = await self.head(identity)
        if metadata is None:
            raise FileNotFoundError(identity.key)
        if metadata.content_length != expected_size:
            raise ValueError("product object size does not match expected_size")
        if metadata.content_type != publication_metadata.content_type:
            raise ValueError(
                "product object content type does not match expected value"
            )
        if (
            metadata.user_metadata.get(_PRODUCT_PUBLICATION_SHA256_METADATA_KEY)
            != publication_metadata.sha256
        ):
            raise ValueError("product object SHA-256 metadata does not match")
        if (
            metadata.user_metadata.get(_PRODUCT_PUBLICATION_ID_METADATA_KEY)
            != publication_metadata.publication_id
        ):
            raise ValueError("product object publication ID metadata does not match")
        return metadata

    async def delete_uncommitted_product_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        publication_metadata: S3ProductPublicationMetadata,
    ) -> None:
        """Conditionally delete only the exact uncommitted product object.

        :param identity: Preallocated product-object destination.
        :param expected_size: Exact verified transfer byte count.
        :param publication_metadata: Exact ownership evidence for this publication.
        """
        metadata = await self.head(identity)
        if metadata is None:
            return
        owned = (
            metadata.content_length == expected_size
            and metadata.content_type == publication_metadata.content_type
            and metadata.user_metadata.get(_PRODUCT_PUBLICATION_SHA256_METADATA_KEY)
            == publication_metadata.sha256
            and metadata.user_metadata.get(_PRODUCT_PUBLICATION_ID_METADATA_KEY)
            == publication_metadata.publication_id
        )
        if not owned:
            return
        if metadata.etag is None:
            raise RuntimeError("product object cleanup requires stable ETag evidence")
        try:
            await self.s3_client.delete_object(
                Bucket=identity.bucket,
                Key=identity.key,
                IfMatch=metadata.etag,
            )
        except BotoClientError as exc:
            if _is_not_found_error(exc):
                return
            if _is_precondition_failed_error(exc):
                raise RuntimeError(
                    "product object changed before conditional cleanup"
                ) from exc
            raise

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

    async def create_preparation_multipart_upload(
        self,
        *,
        destination: S3ObjectIdentity,
        content_type: str | None,
    ) -> S3MultipartUpload:
        """Create a temporary multipart object before its digest is known.

        :param destination: New trusted temporary-object destination.
        :param content_type: Optional MIME type for the temporary object.
        :raises FileExistsError: If the destination already exists.
        :returns: Opaque upload handle.
        """
        await self._ensure_destination_absent(destination)
        response = await self.s3_client.create_multipart_upload(
            Bucket=destination.bucket,
            Key=destination.key,
            **_content_type_args(content_type),
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
            if _is_precondition_failed_error(exc):
                try:
                    await self.abort_multipart_upload(upload=upload)
                except BaseException as cleanup_error:
                    raise S3TransferCleanupRequired(
                        "Multipart upload requires durable abort",
                        multipart_cleanup_required=True,
                        completed_object_cleanup_required=False,
                    ) from cleanup_error
                raise FileExistsError(upload.identity.key) from exc
            try:
                await self._cleanup_failed_completion(
                    upload=upload,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                )
            except S3TransferCleanupRequired as cleanup_error:
                raise cleanup_error from exc
            raise
        except BaseException as exc:
            try:
                await self._cleanup_failed_completion(
                    upload=upload,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                )
            except S3TransferCleanupRequired as cleanup_error:
                if isinstance(exc, asyncio.CancelledError) or isinstance(
                    cleanup_error.__cause__,
                    asyncio.CancelledError,
                ):
                    raise S3TransferCancelled(
                        multipart_cleanup_required=(
                            cleanup_error.multipart_cleanup_required
                        ),
                        completed_object_cleanup_required=(
                            cleanup_error.completed_object_cleanup_required
                        ),
                    ) from exc
                raise cleanup_error from exc
            raise

    async def _cleanup_failed_completion(
        self,
        *,
        upload: S3MultipartUpload,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        """Best-effort both sides of an ambiguous multipart completion."""
        cleanup_error: BaseException | None = None
        multipart_cleanup_required = False
        completed_object_cleanup_required = False
        try:
            await self.abort_multipart_upload(upload=upload)
        except BaseException as exc:
            cleanup_error = exc
            multipart_cleanup_required = True
        try:
            await self._delete_owned_destination(
                upload.identity,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )
        except BaseException as exc:
            completed_object_cleanup_required = True
            if cleanup_error is None:
                cleanup_error = exc
        if cleanup_error is not None:
            raise S3TransferCleanupRequired(
                "Multipart completion requires durable cleanup",
                multipart_cleanup_required=multipart_cleanup_required,
                completed_object_cleanup_required=completed_object_cleanup_required,
            ) from cleanup_error

    async def complete_preparation_multipart_upload(
        self,
        *,
        upload: S3MultipartUpload,
        completed_parts: tuple[S3CompletedPart, ...],
        expected_size: int,
    ) -> S3ObjectMetadata:
        """Complete a digest-unknown temporary object and verify its exact size.

        The temporary object is not a transfer object and carries no transfer
        SHA-256 metadata. Callers must copy it into a verified immutable transfer
        object before marking an attempt READY.

        :param upload: Trusted temporary multipart upload handle.
        :param completed_parts: Ordered completion evidence.
        :param expected_size: Exact completed object size.
        :returns: Persisted temporary-object metadata.
        """
        if expected_size <= 0:
            raise ValueError(
                "preparation multipart completion requires a positive expected_size"
            )
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
        metadata = await self.head(upload.identity)
        if metadata is None:
            raise FileNotFoundError(upload.identity.key)
        if metadata.content_length != expected_size:
            raise ValueError("preparation object size does not match expected_size")
        return metadata

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
            try:
                await self._delete_owned_destination(
                    destination,
                    expected_size=0,
                    expected_sha256=transfer_metadata.sha256,
                )
            except BaseException as cleanup_error:
                raise S3TransferCleanupRequired(
                    "Empty object creation requires durable cleanup",
                    multipart_cleanup_required=False,
                    completed_object_cleanup_required=True,
                ) from cleanup_error
            raise
        except BaseException as exc:
            try:
                await self._delete_owned_destination(
                    destination,
                    expected_size=0,
                    expected_sha256=transfer_metadata.sha256,
                )
            except BaseException as cleanup_error:
                if isinstance(exc, asyncio.CancelledError) or isinstance(
                    cleanup_error,
                    asyncio.CancelledError,
                ):
                    raise S3TransferCancelled(
                        multipart_cleanup_required=False,
                        completed_object_cleanup_required=True,
                    ) from exc
                raise S3TransferCleanupRequired(
                    "Empty object creation requires durable cleanup",
                    multipart_cleanup_required=False,
                    completed_object_cleanup_required=True,
                ) from cleanup_error
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

    async def delete_verified_transfer_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        """Delete one completed transfer object only under exact owned evidence.

        :param identity: completed attempt object identity
        :param expected_size: exact trusted object size
        :param expected_sha256: exact trusted transfer SHA-256
        """
        _validate_sha256(expected_sha256)
        await self._delete_owned_destination(
            identity,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )

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

    async def list_object_summaries_page(
        self,
        *,
        bucket: str,
        prefix: str,
        maximum_keys: int,
        continuation_token: str | None,
    ) -> S3ObjectSummaryPage:
        """Return one bounded page with storage-owned object age evidence.

        :param bucket: Bucket to inspect.
        :param prefix: Object-key prefix.
        :param maximum_keys: Maximum objects in the page.
        :param continuation_token: Token returned by a preceding page.
        :returns: One page and its optional next token.
        """
        _validate_s3_page_size(maximum_keys)
        args: dict[str, Any] = {
            "Bucket": bucket,
            "Prefix": prefix,
            "MaxKeys": maximum_keys,
        }
        if continuation_token is not None:
            args["ContinuationToken"] = continuation_token
        response = await self.s3_client.list_objects_v2(**args)
        objects: list[S3ListedObject] = []
        skipped_entries = 0
        for object_summary in response.get("Contents", []):
            key = _mapping_value(object_summary, "Key")
            last_modified_at = _mapping_value(object_summary, "LastModified")
            if (
                isinstance(key, str)
                and isinstance(last_modified_at, datetime.datetime)
                and _datetime_is_aware(last_modified_at)
            ):
                objects.append(
                    S3ListedObject(
                        identity=S3ObjectIdentity(bucket=bucket, key=key),
                        last_modified_at=last_modified_at,
                    )
                )
            else:
                skipped_entries += 1
        next_token = response.get("NextContinuationToken")
        return S3ObjectSummaryPage(
            objects=tuple(objects),
            next_continuation_token=next_token if isinstance(next_token, str) else None,
            skipped_entries=skipped_entries,
        )

    async def list_multipart_uploads_page(
        self,
        *,
        bucket: str,
        prefix: str,
        maximum_uploads: int,
        key_marker: str | None,
        upload_id_marker: str | None,
    ) -> S3MultipartUploadPage:
        """Return one bounded page of incomplete multipart uploads.

        :param bucket: Bucket to inspect.
        :param prefix: Object-key prefix.
        :param maximum_uploads: Maximum uploads in the page.
        :param key_marker: Key marker returned by a preceding page.
        :param upload_id_marker: Upload marker returned by a preceding page.
        :returns: One page and its optional next markers.
        """
        _validate_s3_page_size(maximum_uploads)
        if key_marker is None and upload_id_marker is not None:
            raise ValueError("upload_id_marker requires key_marker")
        args: dict[str, Any] = {
            "Bucket": bucket,
            "Prefix": prefix,
            "MaxUploads": maximum_uploads,
        }
        if key_marker is not None:
            args["KeyMarker"] = key_marker
        if upload_id_marker is not None:
            args["UploadIdMarker"] = upload_id_marker
        response = await self.s3_client.list_multipart_uploads(**args)
        uploads: list[S3ListedMultipartUpload] = []
        skipped_entries = 0
        for upload_summary in response.get("Uploads", []):
            key = _mapping_value(upload_summary, "Key")
            upload_id = _mapping_value(upload_summary, "UploadId")
            initiated_at = _mapping_value(upload_summary, "Initiated")
            if (
                isinstance(key, str)
                and isinstance(upload_id, str)
                and isinstance(initiated_at, datetime.datetime)
                and _datetime_is_aware(initiated_at)
            ):
                uploads.append(
                    S3ListedMultipartUpload(
                        upload=S3MultipartUpload(
                            identity=S3ObjectIdentity(bucket=bucket, key=key),
                            upload_id=upload_id,
                        ),
                        initiated_at=initiated_at,
                    )
                )
            else:
                skipped_entries += 1
        next_key_marker = response.get("NextKeyMarker")
        next_upload_id_marker = response.get("NextUploadIdMarker")
        return S3MultipartUploadPage(
            uploads=tuple(uploads),
            next_key_marker=(
                next_key_marker if isinstance(next_key_marker, str) else None
            ),
            next_upload_id_marker=(
                next_upload_id_marker
                if isinstance(next_upload_id_marker, str)
                else None
            ),
            skipped_entries=skipped_entries,
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
            if _is_precondition_failed_error(exc):
                raise RuntimeError(
                    "owned destination changed before conditional cleanup"
                ) from exc
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


def _product_publication_user_metadata(
    publication_metadata: S3ProductPublicationMetadata,
) -> dict[str, str]:
    """Return the private metadata required for conditional product cleanup."""
    return {
        _PRODUCT_PUBLICATION_SHA256_METADATA_KEY: publication_metadata.sha256,
        _PRODUCT_PUBLICATION_ID_METADATA_KEY: publication_metadata.publication_id,
    }


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


def _validate_s3_page_size(value: int) -> None:
    if value <= 0 or value > 1000:
        raise ValueError("S3 page size must be between 1 and 1000")


def _datetime_is_aware(value: datetime.datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _mapping_value(value: object, key: str) -> object | None:
    if not isinstance(value, dict):
        return None
    return _known_mapping_value(cast(dict[object, object], value), key)


def _known_mapping_value(
    value: dict[object, object],
    key: str,
) -> object | None:
    return value.get(key)


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
