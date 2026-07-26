"""Tests for S3-native managed Server-to-Runtime source staging."""

from datetime import UTC, datetime, timedelta

import pytest
from azcommon.infra.s3.service import (
    S3ObjectIdentity,
    S3ObjectMetadata,
    S3TransferObjectMetadata,
    S3VerifiedObject,
)
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorOpaqueObjectHandle,
)

from azents.runtime.transfer.managed_source import ManagedServerToRuntimeSource
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeSourceMetadata


class S3CopySpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

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
        self.calls.append(
            {
                "source": source,
                "destination": destination,
                "expected_size": expected_size,
                "transfer_metadata": transfer_metadata,
                "multipart_copy_threshold": multipart_copy_threshold,
                "multipart_part_size": multipart_part_size,
            }
        )
        return S3VerifiedObject(
            metadata=S3ObjectMetadata(
                identity=destination,
                content_length=expected_size,
                content_type="application/octet-stream",
                etag="etag",
                checksum_sha256=None,
                user_metadata={},
                last_modified_at=None,
            ),
            sha256=transfer_metadata.sha256,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", ["exchange", "artifact"])
async def test_managed_source_copies_large_object_without_eager_download(
    source_kind: str,
) -> None:
    s3 = S3CopySpy()
    source = ManagedServerToRuntimeSource(
        metadata=ServerToRuntimeSourceMetadata(
            canonical_uri=f"{source_kind}://opaque",
            source_kind=source_kind,
            display_name="large.bin",
            media_type="application/octet-stream",
            size=4 * 1024 * 1024 + 1,
            sha256="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        ),
        source_identity=S3ObjectIdentity(bucket="workspace", key="private/source"),
        revalidate_authority=_true,
        s3_service=s3,
        bucket="workspace",
        transfer_object_prefix="v1/runtime-transfer",
        multipart_copy_threshold=1024,
        multipart_part_size=1024,
    )

    prepared = await source.prepare(
        admitted_object_handle=CoordinatorOpaqueObjectHandle("admitted")
    )

    assert prepared.size == 4 * 1024 * 1024 + 1
    assert prepared.sha256 == "a" * 64
    assert len(s3.calls) == 1
    call = s3.calls[0]
    assert call["source"] == S3ObjectIdentity(bucket="workspace", key="private/source")
    assert call["destination"] == S3ObjectIdentity(
        bucket="workspace", key="v1/runtime-transfer/admitted"
    )
    assert not hasattr(s3, "download_bytes")
    assert "private/source" not in str(prepared)


@pytest.mark.asyncio
async def test_managed_source_revalidation_rejects_expired_source() -> None:
    source = ManagedServerToRuntimeSource(
        metadata=ServerToRuntimeSourceMetadata(
            "exchange://opaque",
            "exchange",
            "file",
            "text/plain",
            1,
            "a" * 64,
            datetime.now(UTC) - timedelta(seconds=1),
        ),
        source_identity=S3ObjectIdentity(bucket="workspace", key="private/source"),
        revalidate_authority=_true,
        s3_service=S3CopySpy(),
        bucket="workspace",
        transfer_object_prefix="transfer",
        multipart_copy_threshold=1,
        multipart_part_size=1,
    )
    assert await source.revalidate() is False


async def _true() -> bool:
    return True
