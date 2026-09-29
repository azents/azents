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

from azents.runtime.transfer.data import (
    DIRECT_INGRESS_CLEANUP_GRACE,
    RuntimeTransferAdmission,
    RuntimeTransferCleanupStatus,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferObject,
    RuntimeTransferSourceTransport,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore
from azents.runtime.transfer.object_store import RuntimeTransferS3Cleanup

_NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)
_UNTRUSTED_CLEANUP_MESSAGE = (
    "provider=sentinel endpoint=https://storage.example/private-key"
)


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
        self.failure_message = _UNTRUSTED_CLEANUP_MESSAGE

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
            raise RuntimeError(self.failure_message)
        self.deleted.append(key)

    async def abort_multipart_upload(self, *, upload: S3MultipartUpload) -> None:
        if upload.upload_id in self.fail_abort:
            raise RuntimeError(self.failure_message)
        self.aborted.append(upload.upload_id)

    async def delete_verified_transfer_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        """Record verified cleanup through the ordinary fake delete path."""
        del expected_size, expected_sha256
        await self.delete(bucket=identity.bucket, key=identity.key)


@pytest.mark.asyncio
async def test_direct_get_cleanup_preserves_issued_ticket_grace() -> None:
    """Owned transfer objects remain available past the deadline for active GETs."""
    now = _NOW
    store = InMemoryRuntimeTransferStateStore(
        config=RuntimeTransferConfig(
            per_runtime_attempts=2,
            per_runtime_bytes=10,
            deployment_attempts=2,
            deployment_bytes=10,
            admission_lease=timedelta(minutes=5),
            consumer_lease=timedelta(minutes=1),
            stream_lease=timedelta(seconds=30),
            terminal_ttl=timedelta(minutes=5),
            list_page_size=2,
        ),
        clock=lambda: now,
    )
    admitted = await store.admit(
        RuntimeTransferAdmission(
            transfer_id="owned-get",
            attempt_id="attempt",
            direction=RuntimeTransferDirection.DOWNLOAD,
            runtime_id="runtime",
            desired_generation=1,
            operation_id="operation",
            session_id=None,
            agent_id=None,
            runtime_path="/workspace/file",
            overwrite=False,
            conflict_precondition=None,
            expected_size=1,
            expected_sha256=None,
            product_maximum_size=10,
            provider_maximum_size=10,
            deadline_at=_NOW + timedelta(minutes=5),
            source_expires_at=None,
            resource_class="file",
            source_transport=RuntimeTransferSourceTransport.DIRECT_OBJECT,
        ),
        lease_id="lease",
    )
    assert admitted is not None
    ready = await store.mark_ready(
        "owned-get",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        expected_revision=admitted.revision,
        object=RuntimeTransferObject("owned-object", 1, "a" * 64),
    )
    assert ready is not None
    pending = replace(
        ready,
        cleanup_status=RuntimeTransferCleanupStatus.PENDING,
        completed_object_cleanup_required=True,
    )
    object_store = _ObjectStore()
    cleanup = RuntimeTransferS3Cleanup(
        object_store=object_store,
        bucket="bucket",
        object_prefix="v1/runtime-transfer",
        clock=lambda: now,
    )
    with pytest.raises(RuntimeError, match="not yet safe"):
        await cleanup.cleanup(pending)
    assert object_store.deleted == []
    now = admitted.admission.deadline_at + DIRECT_INGRESS_CLEANUP_GRACE
    await cleanup.cleanup(pending)
    assert object_store.deleted == ["v1/runtime-transfer/owned-object"]


@pytest.mark.asyncio
async def test_orphan_repair_uses_one_hour_cutoff_and_bounded_cursors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Old artifacts are cleaned without state while young artifacts remain."""
    object_store = _ObjectStore()
    cleanup = RuntimeTransferS3Cleanup(
        object_store=object_store,
        bucket="bucket",
        object_prefix="/v1/runtime-transfer/",
    )

    with caplog.at_level(
        logging.WARNING,
        logger="azents.runtime.transfer.object_store",
    ):
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
    failed_logs = [
        record
        for record in caplog.records
        if record.message.startswith("Runtime transfer orphan")
        and record.message.endswith("cleanup failed")
    ]
    assert len(failed_logs) == 2
    assert all(record.exc_info is not None for record in failed_logs)
    formatted = [logging.Formatter().format(record) for record in failed_logs]
    assert all(_UNTRUSTED_CLEANUP_MESSAGE not in entry for entry in formatted)


@pytest.mark.asyncio
async def test_orphan_repair_rejects_unbounded_or_unsafe_input() -> None:
    """Orphan repair cannot scan a bucket root or use ambiguous time."""
    object_store = _ObjectStore()
    with pytest.raises(ValueError, match="object prefix"):
        RuntimeTransferS3Cleanup(
            object_store=object_store,
            bucket="bucket",
            object_prefix="/",
        )
    cleanup = RuntimeTransferS3Cleanup(
        object_store=object_store,
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
        object_store=object_store,
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
