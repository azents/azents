"""Internal S3 resolution and multipart cleanup for Runtime transfers."""

from azcommon.infra.s3.service import S3MultipartUpload, S3ObjectIdentity, S3Service

from azents.runtime.transfer.data import RuntimeTransferRecord


class RuntimeTransferS3Cleanup:
    """Abort stale multipart uploads from trusted transfer state only."""

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

    async def abort(self, record: RuntimeTransferRecord) -> None:
        """Abort one stale multipart upload identified by trusted state.

        :param record: exact stale stream record with opaque cleanup evidence
        """
        if record.object is None or record.multipart_cleanup_handle is None:
            raise ValueError("Stale transfer multipart cleanup evidence is unavailable")
        await self._object_store.abort_multipart_upload(
            upload=S3MultipartUpload(
                identity=runtime_transfer_object_identity(
                    bucket=self._bucket,
                    object_prefix=self._object_prefix,
                    opaque_key=record.object.key,
                ),
                upload_id=record.multipart_cleanup_handle,
            )
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
