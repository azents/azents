"""Process-local metadata-only Workspace upload state store."""

import asyncio
import dataclasses
from collections.abc import Callable
from datetime import datetime

from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadAdmission,
    WorkspaceUploadCleanupStatus,
    WorkspaceUploadConfig,
    WorkspaceUploadDeliveryAttempt,
    WorkspaceUploadDeliveryOutcome,
    WorkspaceUploadDestinationEvidence,
    WorkspaceUploadFailure,
    WorkspaceUploadOutcome,
    WorkspaceUploadPage,
    WorkspaceUploadPhase,
    WorkspaceUploadRecord,
    workspace_upload_phase_terminal,
    workspace_upload_terminal_expiry,
)
from azents.runtime.transfer.workspace_upload_object import (
    WorkspaceUploadObjectHandles,
)


class InMemoryWorkspaceUploadStore:
    """One-process Workspace upload store guarded by a single asyncio lock."""

    def __init__(
        self,
        *,
        config: WorkspaceUploadConfig,
        clock: Callable[[], datetime],
    ) -> None:
        """Initialize the bounded volatile store."""
        self.config = config
        self.clock = clock
        self.lock = asyncio.Lock()
        self.records: dict[str, WorkspaceUploadRecord] = {}

    async def create(
        self,
        admission: WorkspaceUploadAdmission,
    ) -> WorkspaceUploadRecord | None:
        """Create one requester-bound upload if active capacity permits it."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            existing = self.records.get(admission.upload_id)
            if existing is not None:
                return existing if existing.admission == admission else None
            if (
                admission.expected_size > self.config.maximum_file_size
                or not self._has_capacity(admission)
            ):
                return None
            record = WorkspaceUploadRecord(
                admission=admission,
                phase=WorkspaceUploadPhase.QUEUED,
                revision=1,
                received_size=0,
                ingress_handle=None,
                source_handle=None,
                actual_size=None,
                actual_sha256=None,
                delivery_attempts=(),
                current_delivery_number=None,
                cancellation_requested_at=None,
                reconciliation_claim_id=None,
                reconciliation_lease_expires_at=None,
                cleanup_claim_id=None,
                cleanup_lease_expires_at=None,
                cleanup_status=WorkspaceUploadCleanupStatus.NOT_REQUIRED,
                cleanup_failure=None,
                outcome=None,
                failure=None,
                created_at=now,
                updated_at=now,
                expires_at=now + self.config.upload_ttl,
                terminal_expires_at=None,
            )
            self.records[admission.upload_id] = record
            return record

    async def get(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
    ) -> WorkspaceUploadRecord | None:
        """Return one exact requester, Workspace, and Agent-bound upload."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            record = self.records.get(upload_id)
            return (
                record
                if _bound(record, requester_user_id, workspace_id, agent_id)
                else None
            )

    async def compare_and_set(
        self,
        record: WorkspaceUploadRecord,
        *,
        expected_revision: int,
    ) -> WorkspaceUploadRecord | None:
        """Atomically replace one record while preserving immutable authority."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            current = self.records.get(record.admission.upload_id)
            if (
                current is None
                or current.revision != expected_revision
                or not _same_authority(current, record)
            ):
                return None
            updated = dataclasses.replace(
                record,
                revision=current.revision + 1,
                updated_at=now,
            )
            self.records[updated.admission.upload_id] = updated
            return updated

    async def claim_ingress(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> WorkspaceUploadRecord | None:
        """Claim one direct-object ingress for authenticated finalization."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            record = self.records.get(upload_id)
            if (
                not _bound(record, requester_user_id, workspace_id, agent_id)
                or record is None
                or record.revision != expected_revision
                or record.phase is not WorkspaceUploadPhase.UPLOADING
                or record.ingress_handle is None
                or record.source_handle is not None
                or record.pending_source_handle is not None
                or record.cancellation_requested_at is not None
                or (
                    record.ingress_claim_id is not None
                    and (
                        record.ingress_lease_expires_at is None
                        or record.ingress_lease_expires_at > now
                    )
                )
                or (
                    record.ingress_claim_id is None
                    and record.ingress_lease_expires_at is not None
                    and record.ingress_lease_expires_at > now
                )
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    ingress_claim_id=claim_id,
                    ingress_lease_expires_at=now + self.config.ingress_lease,
                )
            )

    async def renew_ingress_lease(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> WorkspaceUploadRecord | None:
        """Renew one exact active ingress lease."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            record = self.records.get(upload_id)
            if (
                not _bound(record, requester_user_id, workspace_id, agent_id)
                or record is None
                or record.revision != expected_revision
                or record.phase is not WorkspaceUploadPhase.UPLOADING
                or record.ingress_claim_id != claim_id
                or record.ingress_lease_expires_at is None
                or record.ingress_lease_expires_at <= now
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    ingress_lease_expires_at=now + self.config.ingress_lease,
                )
            )

    async def record_ingress_progress(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
        received_size: int,
    ) -> WorkspaceUploadRecord | None:
        """Record monotonic ingress progress while renewing its lease."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            record = self.records.get(upload_id)
            if (
                not _bound(record, requester_user_id, workspace_id, agent_id)
                or record is None
                or record.revision != expected_revision
                or record.phase is not WorkspaceUploadPhase.UPLOADING
                or record.ingress_claim_id != claim_id
                or record.ingress_lease_expires_at is None
                or record.ingress_lease_expires_at <= now
                or record.cancellation_requested_at is not None
                or received_size < record.received_size
                or received_size > record.admission.expected_size
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    received_size=received_size,
                    ingress_lease_expires_at=now + self.config.ingress_lease,
                )
            )

    async def append_delivery_attempt(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        attempt: WorkspaceUploadDeliveryAttempt,
    ) -> WorkspaceUploadRecord | None:
        """Append exactly one new active immutable Runtime delivery attempt."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            record = self.records.get(upload_id)
            if (
                not _bound(record, requester_user_id, workspace_id, agent_id)
                or record is None
                or record.revision != expected_revision
                or record.source_handle is None
                or record.ingress_claim_id is not None
                or record.phase
                not in {
                    WorkspaceUploadPhase.MOVING_TO_RUNTIME,
                    WorkspaceUploadPhase.CONFLICTED,
                    WorkspaceUploadPhase.RETRYABLE_FAILURE,
                }
                or (
                    record.delivery_attempts
                    and record.delivery_attempts[-1].completed_at is None
                )
                or attempt.number != len(record.delivery_attempts) + 1
                or attempt.completed_at is not None
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    phase=WorkspaceUploadPhase.MOVING_TO_RUNTIME,
                    delivery_attempts=record.delivery_attempts + (attempt,),
                    current_delivery_number=attempt.number,
                    cancellation_requested_at=None,
                    outcome=None,
                    failure=None,
                    terminal_expires_at=None,
                )
            )

    async def settle_delivery_attempt(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        delivery_number: int,
        outcome: WorkspaceUploadDeliveryOutcome,
        failure: WorkspaceUploadFailure | None,
        conflict_precondition: str | None,
        conflict_revision: str | None,
        destination_evidence: WorkspaceUploadDestinationEvidence | None,
    ) -> WorkspaceUploadRecord | None:
        """Settle exactly the current active delivery attempt once."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            record = self.records.get(upload_id)
            if (
                not _bound(record, requester_user_id, workspace_id, agent_id)
                or record is None
                or record.revision != expected_revision
                or record.current_delivery_number != delivery_number
                or not record.delivery_attempts
                or record.delivery_attempts[-1].number != delivery_number
                or record.delivery_attempts[-1].completed_at is not None
            ):
                return None
            active = record.delivery_attempts[-1]
            completed = dataclasses.replace(
                active,
                conflict_precondition=(
                    conflict_precondition
                    if conflict_precondition is not None
                    else active.conflict_precondition
                ),
                completed_at=now,
                outcome=outcome,
                failure=failure,
                conflict_revision=conflict_revision,
                destination_evidence=destination_evidence,
            )
            attempts = record.delivery_attempts[:-1] + (completed,)
            terminal = outcome in {
                WorkspaceUploadDeliveryOutcome.SUCCEEDED,
                WorkspaceUploadDeliveryOutcome.CANCELLED,
                WorkspaceUploadDeliveryOutcome.FAILED,
                WorkspaceUploadDeliveryOutcome.EXPIRED,
            }
            phase = {
                WorkspaceUploadDeliveryOutcome.SUCCEEDED: (
                    WorkspaceUploadPhase.SUCCEEDED
                ),
                WorkspaceUploadDeliveryOutcome.CANCELLED: (
                    WorkspaceUploadPhase.CANCELLED
                ),
                WorkspaceUploadDeliveryOutcome.FAILED: WorkspaceUploadPhase.FAILED,
                WorkspaceUploadDeliveryOutcome.CONFLICTED: (
                    WorkspaceUploadPhase.CONFLICTED
                ),
                WorkspaceUploadDeliveryOutcome.RETRYABLE_FAILURE: (
                    WorkspaceUploadPhase.RETRYABLE_FAILURE
                ),
                WorkspaceUploadDeliveryOutcome.EXPIRED: WorkspaceUploadPhase.EXPIRED,
            }[outcome]
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    phase=phase,
                    delivery_attempts=attempts,
                    reconciliation_claim_id=None,
                    reconciliation_lease_expires_at=None,
                    cancellation_requested_at=None,
                    cleanup_status=(
                        WorkspaceUploadCleanupStatus.PENDING
                        if terminal
                        and (
                            record.source_handle is not None
                            or record.pending_source_handle is not None
                            or record.ingress_handle is not None
                        )
                        else WorkspaceUploadCleanupStatus.NOT_REQUIRED
                    ),
                    cleanup_claim_id=None,
                    cleanup_lease_expires_at=None,
                    cleanup_failure=None,
                    outcome=(
                        WorkspaceUploadOutcome(outcome.value) if terminal else None
                    ),
                    failure=failure,
                    terminal_expires_at=(
                        workspace_upload_terminal_expiry(
                            now,
                            self.config.terminal_ttl,
                        )
                        if terminal
                        else None
                    ),
                )
            )

    async def request_cancellation(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        current_delivery_number: int | None = None,
    ) -> WorkspaceUploadRecord | None:
        """Request cancellation, terminalizing only states with no active worker."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            record = self.records.get(upload_id)
            if (
                not _bound(record, requester_user_id, workspace_id, agent_id)
                or record is None
                or record.revision != expected_revision
                or (
                    current_delivery_number is not None
                    and record.current_delivery_number != current_delivery_number
                )
            ):
                return None
            if workspace_upload_phase_terminal(record.phase):
                return record
            active_worker = (
                record.phase is WorkspaceUploadPhase.UPLOADING
                and record.ingress_claim_id is not None
                and record.ingress_lease_expires_at is not None
                and record.ingress_lease_expires_at > now
            ) or (
                record.phase is WorkspaceUploadPhase.MOVING_TO_RUNTIME
                and bool(record.delivery_attempts)
                and record.delivery_attempts[-1].completed_at is None
            )
            if active_worker:
                return self._put(
                    dataclasses.replace(
                        record,
                        revision=record.revision + 1,
                        updated_at=now,
                        cancellation_requested_at=now,
                    )
                )
            cleanup_required = (
                record.source_handle is not None
                or record.pending_source_handle is not None
                or record.ingress_handle is not None
            )
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    phase=WorkspaceUploadPhase.CANCELLED,
                    cleanup_status=(
                        WorkspaceUploadCleanupStatus.PENDING
                        if cleanup_required
                        else WorkspaceUploadCleanupStatus.NOT_REQUIRED
                    ),
                    cleanup_claim_id=None,
                    cleanup_lease_expires_at=None,
                    cleanup_failure=None,
                    outcome=WorkspaceUploadOutcome.CANCELLED,
                    failure=WorkspaceUploadFailure.CANCELLED,
                    terminal_expires_at=workspace_upload_terminal_expiry(
                        now,
                        self.config.terminal_ttl,
                    ),
                )
            )

    async def claim_reconciliation(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> WorkspaceUploadRecord | None:
        """Claim one active Runtime-delivery projection lease."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            record = self.records.get(upload_id)
            if not _bound(record, requester_user_id, workspace_id, agent_id):
                return None
            assert record is not None
            if (
                record.revision != expected_revision
                or record.phase is not WorkspaceUploadPhase.MOVING_TO_RUNTIME
                or (
                    record.reconciliation_lease_expires_at is not None
                    and record.reconciliation_lease_expires_at > now
                )
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    reconciliation_claim_id=claim_id,
                    reconciliation_lease_expires_at=(
                        now + self.config.reconciliation_lease
                    ),
                )
            )

    async def claim_cleanup(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> WorkspaceUploadRecord | None:
        """Claim one bounded source-cleanup lease."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            record = self.records.get(upload_id)
            if not _bound(record, requester_user_id, workspace_id, agent_id):
                return None
            assert record is not None
            if (
                record.revision != expected_revision
                or record.cleanup_status
                not in {
                    WorkspaceUploadCleanupStatus.PENDING,
                    WorkspaceUploadCleanupStatus.RETRYABLE_FAILURE,
                }
                or (
                    record.cleanup_lease_expires_at is not None
                    and record.cleanup_lease_expires_at > now
                )
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    cleanup_claim_id=claim_id,
                    cleanup_lease_expires_at=now + self.config.cleanup_lease,
                    cleanup_status=WorkspaceUploadCleanupStatus.IN_PROGRESS,
                    cleanup_failure=None,
                )
            )

    async def list_reconciliation(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> WorkspaceUploadPage:
        """List active Runtime-delivery uploads in deterministic identifier order."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            return self._page(
                cursor=cursor,
                limit=limit,
                selected=lambda record: (
                    record.phase is WorkspaceUploadPhase.MOVING_TO_RUNTIME
                ),
            )

    async def list_cleanup(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> WorkspaceUploadPage:
        """List source cleanup candidates in deterministic identifier order."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            return self._page(
                cursor=cursor,
                limit=limit,
                selected=lambda record: (
                    record.cleanup_status
                    in {
                        WorkspaceUploadCleanupStatus.PENDING,
                        WorkspaceUploadCleanupStatus.RETRYABLE_FAILURE,
                    }
                ),
            )

    async def list_object_handles(self) -> WorkspaceUploadObjectHandles:
        """Return all object handles retained by live upload metadata."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            return WorkspaceUploadObjectHandles(
                ingress_handles=frozenset(
                    record.ingress_handle
                    for record in self.records.values()
                    if record.ingress_handle is not None
                ),
                source_handles=frozenset(
                    handle
                    for record in self.records.values()
                    for handle in (
                        record.pending_source_handle,
                        record.source_handle,
                    )
                    if handle is not None
                ),
            )

    async def purge_terminal(self, *, limit: int) -> int:
        """Delete retained terminal metadata only after terminal retention expires."""
        now = self._now()
        async with self.lock:
            self._reclaim(now)
            if limit <= 0 or limit > self.config.list_page_size:
                raise ValueError("invalid page limit")
            keys = [
                upload_id
                for upload_id, record in sorted(self.records.items())
                if (
                    workspace_upload_phase_terminal(record.phase)
                    and record.terminal_expires_at is not None
                    and record.terminal_expires_at <= now
                    and record.cleanup_status
                    in {
                        WorkspaceUploadCleanupStatus.COMPLETE,
                        WorkspaceUploadCleanupStatus.NOT_REQUIRED,
                    }
                )
            ][:limit]
            for upload_id in keys:
                del self.records[upload_id]
            return len(keys)

    def _put(self, record: WorkspaceUploadRecord) -> WorkspaceUploadRecord:
        """Store one already-validated record and return it."""
        self.records[record.admission.upload_id] = record
        return record

    def _reclaim(self, now: datetime) -> None:
        """Expire active metadata without reconstructing state from source residue."""
        for upload_id, record in tuple(self.records.items()):
            if (
                record.phase is WorkspaceUploadPhase.UPLOADING
                and record.ingress_lease_expires_at is not None
                and record.ingress_lease_expires_at <= now
            ):
                cleanup_required = (
                    record.source_handle is not None
                    or record.pending_source_handle is not None
                    or record.ingress_handle is not None
                )
                if record.cancellation_requested_at is not None:
                    self.records[upload_id] = dataclasses.replace(
                        record,
                        phase=WorkspaceUploadPhase.CANCELLED,
                        revision=record.revision + 1,
                        updated_at=now,
                        ingress_claim_id=None,
                        ingress_lease_expires_at=None,
                        cleanup_status=(
                            WorkspaceUploadCleanupStatus.PENDING
                            if cleanup_required
                            else WorkspaceUploadCleanupStatus.NOT_REQUIRED
                        ),
                        outcome=WorkspaceUploadOutcome.CANCELLED,
                        failure=WorkspaceUploadFailure.CANCELLED,
                        terminal_expires_at=workspace_upload_terminal_expiry(
                            now,
                            self.config.terminal_ttl,
                        ),
                    )
                else:
                    self.records[upload_id] = dataclasses.replace(
                        record,
                        phase=WorkspaceUploadPhase.RETRYABLE_FAILURE,
                        revision=record.revision + 1,
                        updated_at=now,
                        ingress_claim_id=None,
                        ingress_lease_expires_at=None,
                        cleanup_status=(
                            WorkspaceUploadCleanupStatus.PENDING
                            if cleanup_required
                            else WorkspaceUploadCleanupStatus.NOT_REQUIRED
                        ),
                        cleanup_claim_id=None,
                        cleanup_lease_expires_at=None,
                        cleanup_failure=None,
                        failure=WorkspaceUploadFailure.INGRESS,
                    )
                continue
            if (
                not workspace_upload_phase_terminal(record.phase)
                and record.expires_at <= now
            ):
                cleanup_status = (
                    WorkspaceUploadCleanupStatus.PENDING
                    if (
                        record.source_handle is not None
                        or record.pending_source_handle is not None
                        or record.ingress_handle is not None
                    )
                    else WorkspaceUploadCleanupStatus.NOT_REQUIRED
                )
                self.records[upload_id] = dataclasses.replace(
                    record,
                    phase=WorkspaceUploadPhase.EXPIRED,
                    revision=record.revision + 1,
                    updated_at=now,
                    reconciliation_claim_id=None,
                    reconciliation_lease_expires_at=None,
                    ingress_claim_id=None,
                    ingress_lease_expires_at=None,
                    cleanup_claim_id=None,
                    cleanup_lease_expires_at=None,
                    cleanup_status=cleanup_status,
                    cleanup_failure=None,
                    outcome=WorkspaceUploadOutcome.EXPIRED,
                    failure=None,
                    terminal_expires_at=workspace_upload_terminal_expiry(
                        now,
                        self.config.terminal_ttl,
                    ),
                )

    def _has_capacity(self, admission: WorkspaceUploadAdmission) -> bool:
        """Apply bounded deployment and requester-Agent active reservations."""
        active = [
            record
            for record in self.records.values()
            if not workspace_upload_phase_terminal(record.phase)
        ]
        scoped = [
            record
            for record in active
            if (
                record.admission.requester_user_id == admission.requester_user_id
                and record.admission.workspace_id == admission.workspace_id
                and record.admission.agent_id == admission.agent_id
            )
        ]
        return (
            len(active) < self.config.maximum_active_uploads
            and sum(record.admission.expected_size for record in active)
            + admission.expected_size
            <= self.config.maximum_active_bytes
            and len(scoped) < self.config.maximum_active_uploads_per_requester_agent
            and sum(record.admission.expected_size for record in scoped)
            + admission.expected_size
            <= self.config.maximum_active_bytes_per_requester_agent
        )

    def _page(
        self,
        *,
        cursor: str | None,
        limit: int,
        selected: Callable[[WorkspaceUploadRecord], bool],
    ) -> WorkspaceUploadPage:
        """Build one deterministic bounded page from current records."""
        if limit <= 0 or limit > self.config.list_page_size:
            raise ValueError("invalid page limit")
        records = [
            record
            for upload_id, record in sorted(self.records.items())
            if (cursor is None or upload_id > cursor) and selected(record)
        ]
        page = tuple(records[:limit])
        return WorkspaceUploadPage(
            records=page,
            cursor=(page[-1].admission.upload_id if len(records) > limit else None),
        )

    def _now(self) -> datetime:
        """Capture one authoritative timezone-aware clock value."""
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return timezone-aware datetime")
        return now


def _bound(
    record: WorkspaceUploadRecord | None,
    requester_user_id: str,
    workspace_id: str,
    agent_id: str,
) -> bool:
    """Return whether a record matches every requester-visible authority boundary."""
    return record is not None and (
        record.admission.requester_user_id,
        record.admission.workspace_id,
        record.admission.agent_id,
    ) == (requester_user_id, workspace_id, agent_id)


def _same_authority(
    current: WorkspaceUploadRecord,
    replacement: WorkspaceUploadRecord,
) -> bool:
    """Prevent CAS callers from changing immutable admission or lifetime authority."""
    return (
        current.admission == replacement.admission
        and current.created_at == replacement.created_at
        and current.expires_at == replacement.expires_at
        and current.delivery_attempts == replacement.delivery_attempts
        and current.current_delivery_number == replacement.current_delivery_number
    )
