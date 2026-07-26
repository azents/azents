"""Internal S3 resolution and multipart cleanup for Runtime transfers."""

from azcommon.infra.s3.service import S3MultipartUpload, S3ObjectIdentity, S3Service

from azents.runtime.transfer.data import (
    RuntimeTransferPreparationCleanupState,
    RuntimeTransferRecord,
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
        self._object_prefix = _prefix(object_prefix)

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
        ):
            raise ValueError("Stale transfer cleanup evidence is unavailable")
        if error is not None:
            raise error


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
