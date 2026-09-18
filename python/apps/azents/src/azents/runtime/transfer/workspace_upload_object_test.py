"""Tests for Workspace upload object cleanup and live-handle fencing."""

from __future__ import annotations

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

from azents.runtime.transfer.workspace_upload_object import (
    WorkspaceUploadObjectHandles,
    WorkspaceUploadObjectOrphanRepair,
    WorkspaceUploadObjectStore,
)
from azents.runtime.transfer.workspace_upload_test_support import _S3

_NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)


def _object_store(s3: _S3) -> WorkspaceUploadObjectStore:
    """Build one bounded object store for reaper tests."""
    return WorkspaceUploadObjectStore(
        s3_service=s3,
        bucket="bucket",
        ingress_object_prefix="workspace-upload-ingress",
        source_object_prefix="workspace-upload-sources",
        ticket_ttl=timedelta(minutes=1),
        multipart_copy_threshold=1,
        multipart_part_size=1,
        clock=lambda: _NOW,
    )


class _AdvancingClock:
    """Return deterministic clock samples to expose double-sampling drift."""

    def __init__(self, *values: datetime) -> None:
        self.values = list(values)

    def __call__(self) -> datetime:
        if not self.values:
            raise AssertionError("clock was sampled more than expected")
        return self.values.pop(0)


@pytest.mark.asyncio
async def test_download_ticket_uses_one_clock_sample_for_deadline() -> None:
    """The direct GET ticket must not exceed its authoritative deadline."""
    deadline_at = _NOW + timedelta(minutes=1)
    s3 = _S3(now=_NOW)
    clock = _AdvancingClock(_NOW, _NOW + timedelta(microseconds=11))
    object_store = WorkspaceUploadObjectStore(
        s3_service=s3,
        bucket="bucket",
        ingress_object_prefix="workspace-upload-ingress",
        source_object_prefix="workspace-upload-sources",
        ticket_ttl=timedelta(minutes=1),
        multipart_copy_threshold=1,
        multipart_part_size=1,
        clock=clock,
    )

    ticket = await object_store.issue_download_ticket(
        source_handle="a" * 32,
        deadline_at=deadline_at,
    )

    assert ticket.expires_at == deadline_at


class _PagedS3(_S3):
    """S3 double with explicit prefix-owned continuation pages."""

    def __init__(self) -> None:
        super().__init__(now=_NOW)
        self.object_pages: dict[tuple[str, str | None], S3ObjectSummaryPage] = {}
        self.multipart_page = S3MultipartUploadPage(
            uploads=(),
            next_key_marker=None,
            next_upload_id_marker=None,
            skipped_entries=0,
        )
        self.object_calls: list[tuple[str, str | None]] = []
        self.multipart_calls: list[tuple[str | None, str | None]] = []

    async def list_object_summaries_page(
        self,
        *,
        bucket: str,
        prefix: str,
        maximum_keys: int,
        continuation_token: str | None,
    ) -> S3ObjectSummaryPage:
        """Return the page selected by its exact prefix and token."""
        del maximum_keys
        self.object_calls.append((prefix, continuation_token))
        return self.object_pages.pop(
            (prefix, continuation_token),
            S3ObjectSummaryPage(
                objects=(),
                next_continuation_token=None,
                skipped_entries=0,
            ),
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
        """Return one deterministic multipart page and record its markers."""
        del bucket, prefix, maximum_uploads
        self.multipart_calls.append((key_marker, upload_id_marker))
        return self.multipart_page


def _listed_object(
    key: str,
    *,
    modified_at: datetime = _NOW - timedelta(hours=1),
) -> S3ListedObject:
    """Build one stale object summary."""
    return S3ListedObject(
        identity=S3ObjectIdentity(bucket="bucket", key=key),
        last_modified_at=modified_at,
    )


def _listed_multipart(
    key: str,
    upload_id: str,
    *,
    initiated_at: datetime = _NOW - timedelta(hours=1),
) -> S3ListedMultipartUpload:
    """Build one stale multipart summary."""
    return S3ListedMultipartUpload(
        upload=S3MultipartUpload(
            identity=S3ObjectIdentity(bucket="bucket", key=key),
            upload_id=upload_id,
        ),
        initiated_at=initiated_at,
    )


@pytest.mark.asyncio
async def test_orphan_repair_keeps_independent_prefix_cursors() -> None:
    """Ingress and source continuation tokens remain scoped to their prefix."""
    s3 = _PagedS3()
    s3.object_pages = {
        (
            "workspace-upload-ingress/",
            None,
        ): S3ObjectSummaryPage(
            objects=(_listed_object("workspace-upload-ingress/one"),),
            next_continuation_token="ingress-next",
            skipped_entries=0,
        ),
        (
            "workspace-upload-sources/",
            None,
        ): S3ObjectSummaryPage(
            objects=(_listed_object("workspace-upload-sources/one"),),
            next_continuation_token="source-next",
            skipped_entries=0,
        ),
        (
            "workspace-upload-ingress/",
            "ingress-next",
        ): S3ObjectSummaryPage(
            objects=(_listed_object("workspace-upload-ingress/two"),),
            next_continuation_token=None,
            skipped_entries=0,
        ),
        (
            "workspace-upload-sources/",
            "source-next",
        ): S3ObjectSummaryPage(
            objects=(_listed_object("workspace-upload-sources/two"),),
            next_continuation_token=None,
            skipped_entries=0,
        ),
    }
    cleanup = WorkspaceUploadObjectOrphanRepair(
        object_store=_object_store(s3),
        live_object_handles=_empty_handles,
    )

    first = await cleanup.repair_orphans(
        now=_NOW,
        maximum_age=timedelta(hours=1),
        page_size=1,
    )
    second = await cleanup.repair_orphans(
        now=_NOW,
        maximum_age=timedelta(hours=1),
        page_size=1,
    )
    third = await cleanup.repair_orphans(
        now=_NOW,
        maximum_age=timedelta(hours=1),
        page_size=1,
    )

    assert first.deleted_objects == 2
    assert second.deleted_objects == 2
    assert third.observed == 0
    assert s3.object_calls == [
        ("workspace-upload-ingress/", None),
        ("workspace-upload-sources/", None),
        ("workspace-upload-ingress/", "ingress-next"),
        ("workspace-upload-sources/", "source-next"),
        ("workspace-upload-ingress/", None),
        ("workspace-upload-sources/", None),
    ]


@pytest.mark.asyncio
async def test_orphan_repair_protects_live_object_handles() -> None:
    """Aged objects remain when metadata authority still retains their handles."""
    s3 = _PagedS3()
    s3.object_pages = {
        (
            "workspace-upload-ingress/",
            None,
        ): S3ObjectSummaryPage(
            objects=(
                _listed_object("workspace-upload-ingress/active-ingress"),
                _listed_object("workspace-upload-ingress/orphan-ingress"),
            ),
            next_continuation_token=None,
            skipped_entries=0,
        ),
        (
            "workspace-upload-sources/",
            None,
        ): S3ObjectSummaryPage(
            objects=(
                _listed_object("workspace-upload-sources/active-source"),
                _listed_object("workspace-upload-sources/pending-source"),
                _listed_object("workspace-upload-sources/orphan-source"),
            ),
            next_continuation_token=None,
            skipped_entries=0,
        ),
    }
    s3.multipart_page = S3MultipartUploadPage(
        uploads=(
            _listed_multipart(
                "workspace-upload-sources/pending-source",
                "pending-upload",
            ),
            _listed_multipart(
                "workspace-upload-sources/orphan-multipart",
                "orphan-upload",
            ),
        ),
        next_key_marker=None,
        next_upload_id_marker=None,
        skipped_entries=0,
    )

    async def live_handles() -> WorkspaceUploadObjectHandles:
        """Return the exact handles currently protected by upload metadata."""
        return WorkspaceUploadObjectHandles(
            ingress_handles=frozenset({"active-ingress"}),
            source_handles=frozenset({"active-source", "pending-source"}),
        )

    cleanup = WorkspaceUploadObjectOrphanRepair(
        object_store=_object_store(s3),
        live_object_handles=live_handles,
    )

    result = await cleanup.repair_orphans(
        now=_NOW,
        maximum_age=timedelta(hours=1),
        page_size=10,
    )

    assert result.listed_objects == 5
    assert result.deleted_objects == 2
    assert result.listed_multipart_uploads == 2
    assert result.aborted_multipart_uploads == 1
    assert result.skipped_storage_entries == 4
    assert [identity.key for identity in s3.deleted] == [
        "workspace-upload-ingress/orphan-ingress",
        "workspace-upload-sources/orphan-source",
    ]
    assert [upload.upload_id for upload in s3.aborted] == ["orphan-upload"]


async def _empty_handles() -> WorkspaceUploadObjectHandles:
    """Return an empty live-handle snapshot for orphan-only tests."""
    return WorkspaceUploadObjectHandles(
        ingress_handles=frozenset(),
        source_handles=frozenset(),
    )
