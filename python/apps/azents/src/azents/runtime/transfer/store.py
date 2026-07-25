"""Runtime transfer state-store contract."""

from datetime import datetime
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

    ``record_progress`` stores only the latest coalesced monotonic observation.
    ``request_cancellation`` is idempotent and makes later successful settlement
    invalid once accepted. An already-terminal attempt remains unchanged.
    """

    async def admit(
        self, admission: RuntimeTransferAdmission, *, lease_id: str, now: datetime
    ) -> RuntimeTransferRecord | None: ...
    async def get(
        self, transfer_id: str, *, now: datetime
    ) -> RuntimeTransferRecord | None: ...
    async def mark_ready(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        expected_revision: int,
        object: RuntimeTransferObject,
        now: datetime,
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
        now: datetime,
    ) -> RuntimeTransferRecord | None: ...
    async def record_progress(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        bytes_transferred: int,
        now: datetime,
    ) -> RuntimeTransferRecord | None: ...
    async def request_cancellation(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        now: datetime,
    ) -> RuntimeTransferRecord | None: ...
    async def begin_verification(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        now: datetime,
    ) -> RuntimeTransferRecord | None: ...
    async def publish_available(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        actual_size: int,
        actual_sha256: str,
        now: datetime,
    ) -> RuntimeTransferRecord | None: ...
    async def mark_committed(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        actual_size: int,
        actual_sha256: str,
        now: datetime,
    ) -> RuntimeTransferRecord | None: ...
    async def claim_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
        now: datetime,
    ) -> RuntimeTransferRecord | None: ...
    async def acknowledge_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
        now: datetime,
    ) -> RuntimeTransferRecord | None: ...
    async def abandon_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
        now: datetime,
    ) -> RuntimeTransferRecord | None: ...
    async def settle(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        outcome: RuntimeTransferOutcome,
        failure: RuntimeTransferFailure | None,
        now: datetime,
    ) -> RuntimeTransferRecord | None: ...
    async def record_cleanup(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        status: RuntimeTransferCleanupStatus,
        now: datetime,
    ) -> RuntimeTransferRecord | None: ...
    async def release_admission(
        self, transfer_id: str, *, attempt_id: str, lease_id: str, now: datetime
    ) -> RuntimeTransferRecord | None: ...
    async def list_stale(
        self, *, cursor: str | None, limit: int, now: datetime
    ) -> RuntimeTransferPage: ...
    async def purge_terminal(self, *, now: datetime, limit: int) -> int: ...
