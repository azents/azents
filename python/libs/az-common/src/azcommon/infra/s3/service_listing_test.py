"""Tests for bounded S3 object and multipart age listings."""

from datetime import UTC, datetime

import pytest

from azcommon.infra.s3.service import S3Service

_MODIFIED = datetime(2026, 7, 28, 10, tzinfo=UTC)
_INITIATED = datetime(2026, 7, 28, 11, tzinfo=UTC)


class _ListingClient:
    """Minimal S3 listing fake."""

    def __init__(self) -> None:
        self.object_calls: list[dict[str, object]] = []
        self.multipart_calls: list[dict[str, object]] = []

    async def list_objects_v2(self, **arguments: object) -> dict[str, object]:
        self.object_calls.append(dict(arguments))
        return {
            "Contents": [
                None,
                {"Key": "runtime-transfer/object", "LastModified": _MODIFIED},
                {"Key": "runtime-transfer/missing-time"},
                {
                    "Key": "runtime-transfer/naive-time",
                    "LastModified": datetime(2026, 7, 28, 10),
                },
            ],
            "NextContinuationToken": "next-object",
        }

    async def list_multipart_uploads(
        self,
        **arguments: object,
    ) -> dict[str, object]:
        self.multipart_calls.append(dict(arguments))
        return {
            "Uploads": [
                None,
                {
                    "Key": "runtime-transfer/multipart",
                    "UploadId": "upload",
                    "Initiated": _INITIATED,
                },
                {
                    "Key": "runtime-transfer/missing-upload",
                    "Initiated": _INITIATED,
                },
                {
                    "Key": "runtime-transfer/naive-upload",
                    "UploadId": "naive",
                    "Initiated": datetime(2026, 7, 28, 11),
                },
            ],
            "NextKeyMarker": "next-key",
            "NextUploadIdMarker": "next-upload",
        }


@pytest.mark.asyncio
async def test_list_object_summaries_preserves_age_and_cursor() -> None:
    """Only complete timezone-aware object summaries are returned."""
    client = _ListingClient()
    service = S3Service(client)  # type: ignore[arg-type]

    page = await service.list_object_summaries_page(
        bucket="bucket",
        prefix="runtime-transfer/",
        maximum_keys=7,
        continuation_token="current",
    )

    assert len(page.objects) == 1
    assert page.objects[0].identity.key == "runtime-transfer/object"
    assert page.objects[0].last_modified_at == _MODIFIED
    assert page.next_continuation_token == "next-object"
    assert page.skipped_entries == 3
    assert client.object_calls == [
        {
            "Bucket": "bucket",
            "Prefix": "runtime-transfer/",
            "MaxKeys": 7,
            "ContinuationToken": "current",
        }
    ]


@pytest.mark.asyncio
async def test_list_multipart_uploads_preserves_age_and_markers() -> None:
    """Only complete timezone-aware multipart summaries are returned."""
    client = _ListingClient()
    service = S3Service(client)  # type: ignore[arg-type]

    page = await service.list_multipart_uploads_page(
        bucket="bucket",
        prefix="runtime-transfer/",
        maximum_uploads=5,
        key_marker="current-key",
        upload_id_marker="current-upload",
    )

    assert len(page.uploads) == 1
    assert page.uploads[0].upload.identity.key == "runtime-transfer/multipart"
    assert page.uploads[0].upload.upload_id == "upload"
    assert page.uploads[0].initiated_at == _INITIATED
    assert page.next_key_marker == "next-key"
    assert page.next_upload_id_marker == "next-upload"
    assert page.skipped_entries == 3
    assert client.multipart_calls == [
        {
            "Bucket": "bucket",
            "Prefix": "runtime-transfer/",
            "MaxUploads": 5,
            "KeyMarker": "current-key",
            "UploadIdMarker": "current-upload",
        }
    ]


@pytest.mark.asyncio
async def test_listing_rejects_invalid_bounds_and_markers() -> None:
    """Listing requires bounded pages and valid multipart marker pairs."""
    service = S3Service(_ListingClient())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="between 1 and 1000"):
        await service.list_object_summaries_page(
            bucket="bucket",
            prefix="runtime-transfer/",
            maximum_keys=1001,
            continuation_token=None,
        )
    with pytest.raises(ValueError, match="requires key_marker"):
        await service.list_multipart_uploads_page(
            bucket="bucket",
            prefix="runtime-transfer/",
            maximum_uploads=1,
            key_marker=None,
            upload_id_marker="upload",
        )
