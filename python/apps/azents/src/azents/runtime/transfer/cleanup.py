"""Expected cleanup deferral for outstanding direct-transfer capabilities."""

from datetime import datetime

from azents.runtime.transfer.data import (
    DIRECT_INGRESS_CLEANUP_GRACE,
    RuntimeTransferDirection,
    RuntimeTransferRecord,
    RuntimeTransferSourceTransport,
)


class RuntimeTransferCleanupDeferred(RuntimeError):
    """Signal expected waiting without reporting skipped deletion as success."""

    def __init__(self, *, safe_at: datetime) -> None:
        """Retain the exact capability protection boundary."""
        super().__init__("Direct transfer cleanup is not yet safe")
        self.safe_at = safe_at


def cleanup_safe_at(record: RuntimeTransferRecord) -> datetime | None:
    """Derive the earliest cleanup time from exact retained capability evidence.

    :param record: trusted transfer attempt and its owned cleanup resources
    :returns: protection boundary, or None when no direct capability protects cleanup
    """
    if record.direct_ingress_handle is not None:
        assert record.direct_ingress_expires_at is not None
        return (
            max(record.direct_ingress_expires_at, record.admission.deadline_at)
            + DIRECT_INGRESS_CLEANUP_GRACE
        )
    if (
        record.admission.direction is RuntimeTransferDirection.DOWNLOAD
        and record.admission.source_transport
        is RuntimeTransferSourceTransport.DIRECT_OBJECT
        and record.admission.source_handle is None
        and record.object is not None
    ):
        return record.admission.deadline_at + DIRECT_INGRESS_CLEANUP_GRACE
    return None
