"""Runtime transfer state-store contract."""

from typing import Protocol

from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCleanupStatus,
    RuntimeTransferFailure,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
    RuntimeTransferPage,
    RuntimeTransferRecord,
)


class RuntimeTransferStateStore(Protocol):
    """Atomic metadata-only transfer state owned by Runtime Control.

    Implementations capture one authoritative timezone-aware clock value for each
    public operation. ``record_progress`` stores only the latest coalesced monotonic
    observation. ``request_cancellation`` is idempotent and makes later successful
    settlement invalid once accepted. An already-terminal attempt remains unchanged.
    """

    async def admit(
        self, admission: RuntimeTransferAdmission, *, lease_id: str
    ) -> RuntimeTransferRecord | None: ...

    async def get(self, transfer_id: str) -> RuntimeTransferRecord | None: ...

    async def mark_ready(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        expected_revision: int,
        object: RuntimeTransferObject,
    ) -> RuntimeTransferRecord | None: ...

    async def claim_stream(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        expected_revision: int,
        claim_id: str,
        owner_replica_id: str,
    ) -> RuntimeTransferRecord | None: ...

    async def bind_dispatch(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        expected_revision: int,
        dispatch_id: str,
        dispatch_request_id: str,
    ) -> RuntimeTransferRecord | None: ...

    async def mark_dispatch_deliverable(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        dispatch_id: str,
        dispatch_request_id: str,
    ) -> RuntimeTransferRecord | None: ...

    async def mark_dispatch_enqueued(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        operation_id: str,
        expected_revision: int,
        dispatch_id: str,
    ) -> RuntimeTransferRecord | None: ...

    async def list_pending_dispatches(
        self, *, cursor: str | None, limit: int
    ) -> RuntimeTransferPage: ...

    async def list_generation_dispatches(
        self, *, cursor: str | None, limit: int
    ) -> RuntimeTransferPage: ...

    async def renew_stream_lease(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        accepted_runner_generation: int,
        expected_revision: int,
        claim_id: str,
        owner_replica_id: str,
    ) -> RuntimeTransferRecord | None: ...

    async def record_multipart_cleanup_handle(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        accepted_runner_generation: int,
        expected_revision: int,
        claim_id: str,
        owner_replica_id: str,
        cleanup_handle: str,
    ) -> RuntimeTransferRecord | None: ...

    async def list_stale_stream_claims(
        self, *, cursor: str | None, limit: int
    ) -> RuntimeTransferPage: ...

    async def record_progress(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        claim_id: str,
        expected_revision: int,
        bytes_transferred: int,
    ) -> RuntimeTransferRecord | None: ...

    async def request_cancellation(
        self, transfer_id: str, *, attempt_id: str, expected_revision: int
    ) -> RuntimeTransferRecord | None: ...

    async def begin_verification(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        claim_id: str,
        expected_revision: int,
    ) -> RuntimeTransferRecord | None: ...

    async def publish_available(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        claim_id: str,
        expected_revision: int,
        actual_size: int,
        actual_sha256: str,
    ) -> RuntimeTransferRecord | None: ...

    async def mark_committed(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        claim_id: str,
        expected_revision: int,
        actual_size: int,
        actual_sha256: str,
    ) -> RuntimeTransferRecord | None: ...

    async def claim_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> RuntimeTransferRecord | None: ...

    async def acknowledge_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> RuntimeTransferRecord | None: ...

    async def abandon_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> RuntimeTransferRecord | None: ...

    async def settle(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        outcome: RuntimeTransferOutcome,
        failure: RuntimeTransferFailure | None,
    ) -> RuntimeTransferRecord | None: ...

    async def record_cleanup(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        status: RuntimeTransferCleanupStatus,
    ) -> RuntimeTransferRecord | None: ...

    async def release_admission(
        self, transfer_id: str, *, attempt_id: str, lease_id: str
    ) -> RuntimeTransferRecord | None: ...

    async def list_stale(
        self, *, cursor: str | None, limit: int
    ) -> RuntimeTransferPage: ...

    async def purge_terminal(self, *, limit: int) -> int: ...
