"""Internal S3 resolution and multipart cleanup for Runtime transfers."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from azcommon.infra.s3.service import S3MultipartUpload, S3ObjectIdentity, S3Service

from azents.runtime.transfer.data import (
    RUNTIME_TRANSFER_MAXIMUM_PAGE_SIZE,
    RuntimeTransferPreparationCleanupState,
    RuntimeTransferRecord,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeTransferOrphanRepairResult:
    """Bounded aggregate evidence from one state-independent prefix scan."""

    listed_objects: int
    deleted_objects: int
    listed_multipart_uploads: int
    aborted_multipart_uploads: int
    failed_cleanups: int
    skipped_storage_entries: int

    @property
    def observed(self) -> int:
        """Return the total listed artifact count."""
        return (
            self.listed_objects
            + self.listed_multipart_uploads
            + self.skipped_storage_entries
        )


class RuntimeTransferS3Cleanup:
    """Clean stale multipart and completed-object work from trusted state."""

    def __init__(
        self,
        *,
        object_store: S3Service,
        bucket: str,
        object_prefix: str,
    ) -> None:
        """Initialize trusted S3 cleanup dependencies.

        :param object_store: process-owned trusted S3 service
        :param bucket: Control-selected workspace bucket
        :param object_prefix: internal transfer-object key namespace
        """
        self._object_store = object_store
        self._bucket = _required(bucket, "Runtime transfer bucket")
        self._object_prefix = _required(
            _prefix(object_prefix),
            "Runtime transfer object prefix",
        )
        self._object_continuation_token: str | None = None
        self._multipart_key_marker: str | None = None
        self._multipart_upload_id_marker: str | None = None

    async def cleanup(self, record: RuntimeTransferRecord) -> None:
        """Clean one exact stale upload artifact identified by trusted state.

        :param record: exact stale stream record with trusted cleanup evidence
        """
        error: BaseException | None = None
        if record.preparation_object_handle is not None:
            preparation_identity = runtime_transfer_object_identity(
                bucket=self._bucket,
                object_prefix=self._object_prefix,
                opaque_key=record.preparation_object_handle,
            )
            if (
                record.preparation_cleanup_state
                is RuntimeTransferPreparationCleanupState.MULTIPART_PENDING
            ):
                assert record.preparation_multipart_cleanup_handle is not None
                try:
                    await self._object_store.abort_multipart_upload(
                        upload=S3MultipartUpload(
                            identity=preparation_identity,
                            upload_id=record.preparation_multipart_cleanup_handle,
                        )
                    )
                except BaseException as exc:
                    error = exc
            elif (
                record.preparation_cleanup_state
                is RuntimeTransferPreparationCleanupState.COMPLETED_OBJECT_PENDING
            ):
                try:
                    await self._object_store.delete(
                        bucket=preparation_identity.bucket,
                        key=preparation_identity.key,
                    )
                except BaseException as exc:
                    error = exc
        if record.pre_ready_object_handle is not None:
            pre_ready_identity = runtime_transfer_object_identity(
                bucket=self._bucket,
                object_prefix=self._object_prefix,
                opaque_key=record.pre_ready_object_handle,
            )
            try:
                await self._object_store.delete(
                    bucket=pre_ready_identity.bucket,
                    key=pre_ready_identity.key,
                )
            except BaseException as exc:
                if error is None:
                    error = exc
        if record.object is not None:
            identity = runtime_transfer_object_identity(
                bucket=self._bucket,
                object_prefix=self._object_prefix,
                opaque_key=record.object.key,
            )
        else:
            identity = None
        if record.multipart_cleanup_handle is not None:
            if identity is None:
                raise ValueError(
                    "Stale transfer multipart cleanup object is unavailable"
                )
            try:
                await self._object_store.abort_multipart_upload(
                    upload=S3MultipartUpload(
                        identity=identity,
                        upload_id=record.multipart_cleanup_handle,
                    )
                )
            except BaseException as exc:
                error = exc
        if record.completed_object_cleanup_required:
            object = record.object
            if identity is None or object is None:
                raise ValueError(
                    "Stale transfer object cleanup evidence is unavailable"
                )
            try:
                if object.sha256 is None:
                    await self._object_store.delete(
                        bucket=identity.bucket,
                        key=identity.key,
                    )
                else:
                    await self._object_store.delete_verified_transfer_object(
                        identity=identity,
                        expected_size=object.size,
                        expected_sha256=object.sha256,
                    )
            except BaseException as exc:
                if error is None:
                    error = exc
        if (
            record.preparation_cleanup_state
            is RuntimeTransferPreparationCleanupState.NOT_REQUIRED
            and record.multipart_cleanup_handle is None
            and not record.completed_object_cleanup_required
            and record.pre_ready_object_handle is None
        ):
            raise ValueError("Stale transfer cleanup evidence is unavailable")
        if error is not None:
            raise error

    async def repair_orphans(
        self,
        *,
        now: datetime,
        maximum_age: timedelta,
        page_size: int,
    ) -> RuntimeTransferOrphanRepairResult:
        """Clean one bounded page of state-independent expired artifacts.

        :param now: Authoritative timezone-aware repair time
        :param maximum_age: Minimum storage-reported artifact age for cleanup
        :param page_size: Maximum objects and uploads listed per category
        :returns: Bounded aggregate cleanup evidence
        """
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError(
                "Runtime transfer orphan repair time must be timezone-aware"
            )
        if maximum_age <= timedelta():
            raise ValueError("Runtime transfer orphan maximum age must be positive")
        if page_size <= 0 or page_size > RUNTIME_TRANSFER_MAXIMUM_PAGE_SIZE:
            raise ValueError(
                "Runtime transfer orphan page size must be between 1 and 1000"
            )
        cutoff = now - maximum_age
        prefix = f"{self._object_prefix}/"
        object_page = await self._object_store.list_object_summaries_page(
            bucket=self._bucket,
            prefix=prefix,
            maximum_keys=page_size,
            continuation_token=self._object_continuation_token,
        )
        deleted_objects = 0
        failed_cleanups = 0
        for listed in object_page.objects:
            if listed.last_modified_at > cutoff:
                continue
            try:
                await self._object_store.delete(
                    bucket=listed.identity.bucket,
                    key=listed.identity.key,
                )
                deleted_objects += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                failed_cleanups += 1
                _LOGGER.exception(
                    "Runtime transfer orphan object cleanup failed",
                    extra={"artifact_kind": "object"},
                )
        self._object_continuation_token = object_page.next_continuation_token
        if object_page.skipped_entries:
            _LOGGER.warning(
                "Runtime transfer orphan listing skipped invalid age evidence",
                extra={
                    "artifact_kind": "object",
                    "skipped_entries": object_page.skipped_entries,
                },
            )

        multipart_page = await self._object_store.list_multipart_uploads_page(
            bucket=self._bucket,
            prefix=prefix,
            maximum_uploads=page_size,
            key_marker=self._multipart_key_marker,
            upload_id_marker=self._multipart_upload_id_marker,
        )
        aborted_multipart_uploads = 0
        for listed in multipart_page.uploads:
            if listed.initiated_at > cutoff:
                continue
            try:
                await self._object_store.abort_multipart_upload(upload=listed.upload)
                aborted_multipart_uploads += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                failed_cleanups += 1
                _LOGGER.exception(
                    "Runtime transfer orphan multipart cleanup failed",
                    extra={"artifact_kind": "multipart_upload"},
                )
        self._multipart_key_marker = multipart_page.next_key_marker
        self._multipart_upload_id_marker = multipart_page.next_upload_id_marker
        if multipart_page.skipped_entries:
            _LOGGER.warning(
                "Runtime transfer orphan listing skipped invalid age evidence",
                extra={
                    "artifact_kind": "multipart_upload",
                    "skipped_entries": multipart_page.skipped_entries,
                },
            )
        return RuntimeTransferOrphanRepairResult(
            listed_objects=len(object_page.objects),
            deleted_objects=deleted_objects,
            listed_multipart_uploads=len(multipart_page.uploads),
            aborted_multipart_uploads=aborted_multipart_uploads,
            failed_cleanups=failed_cleanups,
            skipped_storage_entries=(
                object_page.skipped_entries + multipart_page.skipped_entries
            ),
        )


def runtime_transfer_object_identity(
    *,
    bucket: str,
    object_prefix: str,
    opaque_key: str,
) -> S3ObjectIdentity:
    """Resolve one state-owned opaque handle into an internal S3 identity.

    :param bucket: Control-selected workspace bucket
    :param object_prefix: internal transfer-object key namespace
    :param opaque_key: trusted state-owned opaque object handle
    :returns: internal S3 object identity
    """
    return S3ObjectIdentity(
        bucket=_required(bucket, "Runtime transfer bucket"),
        key="/".join(
            value
            for value in (_prefix(object_prefix), _required(opaque_key, "Opaque key"))
            if value
        ),
    )


def _prefix(value: str) -> str:
    prefix = value.strip("/")
    if not prefix:
        return ""
    if any(part in {".", ".."} for part in prefix.split("/")):
        raise ValueError("Runtime transfer object prefix is invalid")
    return prefix


def _required(value: str, name: str) -> str:
    if not value:
        raise ValueError(f"{name} is required")
    return value
