"""Real RustFS coverage for bounded Runtime transfer S3 primitives."""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import aioboto3
import pytest
from azcommon.infra.s3.service import (
    S3ObjectIdentity,
    S3Service,
    S3TransferObjectMetadata,
)
from testcontainers.core.container import DockerContainer


@asynccontextmanager
async def _service(
    *,
    rustfs_container: DockerContainer,
    access_key: str,
    secret_key: str,
) -> AsyncIterator[S3Service]:
    """Open one async S3 service connected to the RustFS test container."""
    session = aioboto3.Session()
    endpoint_url = (
        f"http://{rustfs_container.get_container_host_ip()}:"
        f"{rustfs_container.get_exposed_port(9000)}"
    )
    async with session.client(  # pyright: ignore[reportUnknownMemberType] # aioboto3 generated overload returns Unknown
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    ) as client:
        yield S3Service(s3_client=client)


def _key(name: str) -> str:
    """Return an isolated test key."""
    return f"runtime-transfer-storage/{uuid4().hex}/{name}"


def _sha256(body: bytes) -> str:
    """Return the hexadecimal SHA-256 digest for bytes."""
    return hashlib.sha256(body).hexdigest()


@pytest.mark.asyncio
async def test_rustfs_head_bounded_read_and_not_found(
    rustfs_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    s3_bucket_name: str,
) -> None:
    """HEAD and bounded reads return metadata and actual byte evidence."""
    body = b"bounded-rustfs-body" * 100
    identity = S3ObjectIdentity(bucket=s3_bucket_name, key=_key("source"))
    async with _service(
        rustfs_container=rustfs_container,
        access_key=rustfs_access_key,
        secret_key=rustfs_secret_key,
    ) as service:
        await service.upload(
            identity.bucket, identity.key, body, content_type="text/plain"
        )

        assert (
            await service.head(
                S3ObjectIdentity(bucket=s3_bucket_name, key=_key("missing"))
            )
            is None
        )
        metadata = await service.head(identity)
        assert metadata is not None
        assert metadata.content_length == len(body)
        assert metadata.content_type == "text/plain"

        digest = hashlib.sha256()
        async with service.iter_chunks(identity, maximum_chunk_size=17) as chunks:
            async for chunk in chunks:
                assert len(chunk) <= 17
                digest.update(chunk)

        assert digest.hexdigest() == _sha256(body)


@pytest.mark.asyncio
async def test_rustfs_immutable_copy_replaces_metadata_and_verifies_bytes(
    rustfs_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    s3_bucket_name: str,
) -> None:
    """Normal immutable copy strips source metadata and preserves actual bytes."""
    body = b"normal-copy-body"
    digest = _sha256(body)
    source = S3ObjectIdentity(bucket=s3_bucket_name, key=_key("source"))
    destination = S3ObjectIdentity(bucket=s3_bucket_name, key=_key("destination"))
    async with _service(
        rustfs_container=rustfs_container,
        access_key=rustfs_access_key,
        secret_key=rustfs_secret_key,
    ) as service:
        await service.s3_client.put_object(
            Bucket=source.bucket,
            Key=source.key,
            Body=body,
            Metadata={"untrusted": "must-not-copy"},
        )
        verified = await service.copy_immutable(
            source=source,
            destination=destination,
            expected_size=len(body),
            transfer_metadata=S3TransferObjectMetadata(
                sha256=digest,
                content_type="application/octet-stream",
            ),
            multipart_copy_threshold=len(body),
            multipart_part_size=5 * 1024 * 1024,
        )

        assert verified.metadata.user_metadata == {"azents-transfer-sha256": digest}
        assert verified.metadata.content_type == "application/octet-stream"
        async with service.iter_chunks(destination, maximum_chunk_size=1024) as chunks:
            actual = b"".join([chunk async for chunk in chunks])
        assert _sha256(actual) == digest


@pytest.mark.asyncio
async def test_rustfs_multipart_upload_copy_abort_zero_byte_and_cleanup(
    rustfs_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    s3_bucket_name: str,
) -> None:
    """RustFS supports transfer multipart lifecycle, copy, abort, and cleanup."""
    first_part = b"a" * (5 * 1024 * 1024)
    body = first_part + b"tail"
    digest = _sha256(body)
    upload_destination = S3ObjectIdentity(bucket=s3_bucket_name, key=_key("upload"))
    copy_destination = S3ObjectIdentity(bucket=s3_bucket_name, key=_key("copy"))
    abort_destination = S3ObjectIdentity(bucket=s3_bucket_name, key=_key("abort"))
    empty_destination = S3ObjectIdentity(bucket=s3_bucket_name, key=_key("empty"))
    async with _service(
        rustfs_container=rustfs_container,
        access_key=rustfs_access_key,
        secret_key=rustfs_secret_key,
    ) as service:
        metadata = S3TransferObjectMetadata(sha256=digest, content_type=None)
        upload = await service.create_multipart_upload(
            destination=upload_destination,
            transfer_metadata=metadata,
        )
        parts = (
            await service.upload_part(upload=upload, part_number=1, body=first_part),
            await service.upload_part(upload=upload, part_number=2, body=b"tail"),
        )
        verified = await service.complete_multipart_upload(
            upload=upload,
            completed_parts=parts,
            expected_size=len(body),
            expected_sha256=digest,
        )
        assert verified.metadata.content_length == len(body)
        uploaded_hasher = hashlib.sha256()
        async with service.iter_chunks(
            upload_destination, maximum_chunk_size=1024 * 1024
        ) as chunks:
            async for chunk in chunks:
                uploaded_hasher.update(chunk)
        assert uploaded_hasher.hexdigest() == digest
        object_page = await service.list_object_summaries_page(
            bucket=s3_bucket_name,
            prefix=upload_destination.key,
            maximum_keys=1,
            continuation_token=None,
        )
        assert len(object_page.objects) == 1
        assert object_page.objects[0].identity == upload_destination
        assert object_page.objects[0].last_modified_at.utcoffset() is not None

        copied = await service.copy_immutable(
            source=upload_destination,
            destination=copy_destination,
            expected_size=len(body),
            transfer_metadata=metadata,
            multipart_copy_threshold=1,
            multipart_part_size=5 * 1024 * 1024,
        )
        assert copied.sha256 == digest
        copied_hasher = hashlib.sha256()
        async with service.iter_chunks(
            copy_destination, maximum_chunk_size=1024 * 1024
        ) as chunks:
            async for chunk in chunks:
                copied_hasher.update(chunk)
        assert copied_hasher.hexdigest() == digest

        aborted = await service.create_multipart_upload(
            destination=abort_destination,
            transfer_metadata=metadata,
        )
        await service.upload_part(upload=aborted, part_number=1, body=first_part)
        multipart_page = await service.list_multipart_uploads_page(
            bucket=s3_bucket_name,
            prefix=abort_destination.key,
            maximum_uploads=1,
            key_marker=None,
            upload_id_marker=None,
        )
        assert len(multipart_page.uploads) == 1
        assert multipart_page.uploads[0].upload == aborted
        assert multipart_page.uploads[0].initiated_at.utcoffset() is not None
        await service.abort_multipart_upload(upload=aborted)
        assert await service.head(abort_destination) is None

        empty_digest = _sha256(b"")
        empty = await service.create_empty_immutable(
            destination=empty_destination,
            transfer_metadata=S3TransferObjectMetadata(
                sha256=empty_digest,
                content_type="text/plain",
            ),
        )
        assert empty.metadata.content_length == 0

        cleanup_prefix = _key("cleanup/")
        for index in range(3):
            await service.upload(s3_bucket_name, f"{cleanup_prefix}{index}", b"x")
        deleted = 0
        continuation_token: str | None = None
        while True:
            cleanup = await service.delete_prefix_bounded(
                bucket=s3_bucket_name,
                prefix=cleanup_prefix,
                page_size=2,
                continuation_token=continuation_token,
            )
            deleted += len(cleanup.deleted)
            assert not cleanup.failed
            continuation_token = cleanup.next_continuation_token
            if continuation_token is None:
                break
        assert deleted == 3
        page = await service.list_page(
            bucket=s3_bucket_name,
            prefix=cleanup_prefix,
            maximum_keys=2,
            continuation_token=None,
        )
        assert not page.objects
