"""Tests for exact and state-independent Runtime transfer S3 cleanup."""

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from azcommon.infra.s3.service import (
    S3ListedMultipartUpload,
    S3ListedObject,
    S3MultipartUpload,
    S3MultipartUploadPage,
    S3ObjectIdentity,
    S3ObjectSummaryPage,
)

from azents.runtime.transfer.object_store import RuntimeTransferS3Cleanup

_NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)


class _ObjectStore:
    """Bounded fake for state-independent orphan cleanup."""

    def __init__(self) -> None:
        self.object_pages = [
            S3ObjectSummaryPage(
                objects=(
                    _listed_object("v1/runtime-transfer/old", minutes=60),
                    _listed_object("v1/runtime-transfer/young", minutes=59),
                ),
                next_continuation_token="objects-next",
                skipped_entries=0,
            ),
            S3ObjectSummaryPage(
                objects=(
                    _listed_object("v1/runtime-transfer/retry", minutes=120),
                    _listed_object(
                        "v1/runtime-transfer/after-retry",
                        minutes=120,
                    ),
                ),
                next_continuation_token=None,
                skipped_entries=0,
            ),
        ]
        self.multipart_pages = [
            S3MultipartUploadPage(
                uploads=(
                    _listed_upload(
                        "v1/runtime-transfer/old-multipart",
                        "upload-old",
                        minutes=61,
                    ),
                    _listed_upload(
                        "v1/runtime-transfer/young-multipart",
                        "upload-young",
                        minutes=59,
                    ),
                ),
                next_key_marker="multipart-next",
                next_upload_id_marker="upload-next",
                skipped_entries=0,
            ),
            S3MultipartUploadPage(
                uploads=(
                    _listed_upload(
                        "v1/runtime-transfer/retry-multipart",
                        "upload-retry",
                        minutes=120,
                    ),
                    _listed_upload(
                        "v1/runtime-transfer/after-retry-multipart",
                        "upload-after-retry",
                        minutes=120,
                    ),
                ),
                next_key_marker=None,
                next_upload_id_marker=None,
                skipped_entries=0,
            ),
        ]
        self.object_calls: list[tuple[str, str, int, str | None]] = []
        self.multipart_calls: list[tuple[str, str, int, str | None, str | None]] = []
        self.deleted: list[str] = []
        self.aborted: list[str] = []
        self.fail_delete = {"v1/runtime-transfer/retry"}
        self.fail_abort = {"upload-retry"}

    async def list_object_summaries_page(
        self,
        *,
        bucket: str,
        prefix: str,
        maximum_keys: int,
        continuation_token: str | None,
    ) -> S3ObjectSummaryPage:
        self.object_calls.append((bucket, prefix, maximum_keys, continuation_token))
        return self.object_pages.pop(0)

    async def list_multipart_uploads_page(
        self,
        *,
        bucket: str,
        prefix: str,
        maximum_uploads: int,
        key_marker: str | None,
        upload_id_marker: str | None,
    ) -> S3MultipartUploadPage:
        self.multipart_calls.append(
            (bucket, prefix, maximum_uploads, key_marker, upload_id_marker)
        )
        return self.multipart_pages.pop(0)

    async def delete(self, *, bucket: str, key: str) -> None:
        assert bucket == "bucket"
        if key in self.fail_delete:
            raise RuntimeError("delete unavailable")
        self.deleted.append(key)

    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None:
        if upload.upload_id in self.fail_abort:
            raise RuntimeError("abort unavailable")
        self.aborted.append(upload.upload_id)


@pytest.mark.asyncio
async def test_orphan_repair_uses_one_hour_cutoff_and_bounded_cursors() -> None:
    """Old artifacts are cleaned without state while young artifacts remain."""
    object_store = _ObjectStore()
    cleanup = RuntimeTransferS3Cleanup(
        object_store=object_store,  # type: ignore[arg-type]
        bucket="bucket",
        object_prefix="/v1/runtime-transfer/",
    )

    first = await cleanup.repair_orphans(
        now=_NOW,
        maximum_age=timedelta(hours=1),
        page_size=2,
    )
    second = await cleanup.repair_orphans(
        now=_NOW,
        maximum_age=timedelta(hours=1),
        page_size=2,
    )

    assert first.listed_objects == 2
    assert first.deleted_objects == 1
    assert first.listed_multipart_uploads == 2
    assert first.aborted_multipart_uploads == 1
    assert first.failed_cleanups == 0
    assert second.observed == 4
    assert second.deleted_objects == 1
    assert second.aborted_multipart_uploads == 1
    assert second.failed_cleanups == 2
    assert object_store.deleted == [
        "v1/runtime-transfer/old",
        "v1/runtime-transfer/after-retry",
    ]
    assert object_store.aborted == ["upload-old", "upload-after-retry"]
    assert object_store.object_calls == [
        ("bucket", "v1/runtime-transfer/", 2, None),
        ("bucket", "v1/runtime-transfer/", 2, "objects-next"),
    ]
    assert object_store.multipart_calls == [
        ("bucket", "v1/runtime-transfer/", 2, None, None),
        (
            "bucket",
            "v1/runtime-transfer/",
            2,
            "multipart-next",
            "upload-next",
        ),
    ]


@pytest.mark.asyncio
async def test_orphan_repair_rejects_unbounded_or_unsafe_input() -> None:
    """Orphan repair cannot scan a bucket root or use ambiguous time."""
    object_store = _ObjectStore()
    with pytest.raises(ValueError, match="object prefix"):
        RuntimeTransferS3Cleanup(
            object_store=object_store,  # type: ignore[arg-type]
            bucket="bucket",
            object_prefix="/",
        )
    cleanup = RuntimeTransferS3Cleanup(
        object_store=object_store,  # type: ignore[arg-type]
        bucket="bucket",
        object_prefix="runtime-transfer",
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        await cleanup.repair_orphans(
            now=datetime(2026, 7, 28, 12),
            maximum_age=timedelta(hours=1),
            page_size=1,
        )
    with pytest.raises(ValueError, match="positive"):
        await cleanup.repair_orphans(
            now=_NOW,
            maximum_age=timedelta(),
            page_size=1,
        )
    with pytest.raises(ValueError, match="between 1 and 1000"):
        await cleanup.repair_orphans(
            now=_NOW,
            maximum_age=timedelta(hours=1),
            page_size=1001,
        )


@pytest.mark.asyncio
async def test_orphan_repair_logs_skipped_storage_age_evidence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Malformed storage timestamps remain visible without unsafe deletion."""
    object_store = _ObjectStore()
    object_store.object_pages[0] = replace(
        object_store.object_pages[0],
        objects=(),
        skipped_entries=2,
    )
    object_store.multipart_pages[0] = replace(
        object_store.multipart_pages[0],
        uploads=(),
        skipped_entries=3,
    )
    cleanup = RuntimeTransferS3Cleanup(
        object_store=object_store,  # type: ignore[arg-type]
        bucket="bucket",
        object_prefix="runtime-transfer",
    )

    with caplog.at_level(
        logging.WARNING,
        logger="azents.runtime.transfer.object_store",
    ):
        result = await cleanup.repair_orphans(
            now=_NOW,
            maximum_age=timedelta(hours=1),
            page_size=2,
        )

    assert result.skipped_storage_entries == 5
    assert result.observed == 5
    assert [
        (
            record.__dict__["artifact_kind"],
            record.__dict__["skipped_entries"],
        )
        for record in caplog.records
    ] == [("object", 2), ("multipart_upload", 3)]


def _listed_object(key: str, *, minutes: int) -> S3ListedObject:
    return S3ListedObject(
        identity=S3ObjectIdentity(bucket="bucket", key=key),
        last_modified_at=_NOW - timedelta(minutes=minutes),
    )


def _listed_upload(
    key: str,
    upload_id: str,
    *,
    minutes: int,
) -> S3ListedMultipartUpload:
    return S3ListedMultipartUpload(
        upload=S3MultipartUpload(
            identity=S3ObjectIdentity(bucket="bucket", key=key),
            upload_id=upload_id,
        ),
        initiated_at=_NOW - timedelta(minutes=minutes),
    )
