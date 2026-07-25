"""Process-local metadata-only Runtime transfer state store."""

import asyncio
import base64
import dataclasses
import json
from bisect import bisect_right
from collections.abc import Callable
from datetime import datetime

from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCleanupStatus,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferDispatchStatus,
    RuntimeTransferFailure,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
    RuntimeTransferPage,
    RuntimeTransferPhase,
    RuntimeTransferProgress,
    RuntimeTransferRecord,
    logical_expiry,
    terminal_expiry,
    validate_admission_time,
)
from azents.runtime.transfer.policy import phase_transition_allowed


class InMemoryRuntimeTransferStateStore:
    """One-process transfer store guarded by a single asyncio lock."""

    def __init__(
        self,
        *,
        config: RuntimeTransferConfig,
        clock: Callable[[], datetime],
    ) -> None:
        self.config = config
        self.clock = clock
        self.lock = asyncio.Lock()
        self.records: dict[tuple[str, str], RuntimeTransferRecord] = {}
        self.current_attempts: dict[str, str] = {}
        self.released: set[tuple[str, str]] = set()

    async def admit(
        self, admission: RuntimeTransferAdmission, *, lease_id: str
    ) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            self._expire(now)
            try:
                validate_admission_time(admission, now)
            except ValueError:
                return None
            key = (admission.transfer_id, admission.attempt_id)
            existing = self.records.get(key)
            if existing is not None:
                return existing
            current = self._current(admission.transfer_id)
            if (
                current is not None
                and current.phase is not RuntimeTransferPhase.TERMINAL
            ):
                return None
            if admission.expected_size > min(
                admission.product_maximum_size, admission.provider_maximum_size
            ):
                return None
            if not self._has_capacity(admission):
                return None
            record = RuntimeTransferRecord(
                admission=admission,
                phase=RuntimeTransferPhase.PREPARING,
                revision=1,
                lease_id=lease_id,
                lease_expires_at=now + self.config.admission_lease,
                created_at=now,
                updated_at=now,
                logical_expires_at=logical_expiry(now, admission.source_expires_at),
                accepted_runner_generation=None,
                dispatch_id=None,
                dispatch_status=RuntimeTransferDispatchStatus.NOT_BOUND,
                dispatch_request_id=None,
                object=None,
                actual_size=None,
                actual_sha256=None,
                stream_claim_id=None,
                stream_owner_replica_id=None,
                stream_lease_expires_at=None,
                multipart_cleanup_handle=None,
                progress=None,
                cancellation_requested_at=None,
                consumer_claim_id=None,
                consumer_lease_expires_at=None,
                consumer_acknowledged_at=None,
                terminal_outcome=None,
                terminal_expires_at=None,
                cleanup_status=RuntimeTransferCleanupStatus.NOT_REQUIRED,
                failure=None,
            )
            self.records[key] = record
            self.current_attempts[admission.transfer_id] = admission.attempt_id
            return record

    async def get(self, transfer_id: str) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            self._expire(now)
            return self._current(transfer_id)

    async def mark_ready(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        expected_revision: int,
        object: RuntimeTransferObject,
    ) -> RuntimeTransferRecord | None:
        return await self._move(
            transfer_id,
            attempt_id,
            expected_revision,
            RuntimeTransferPhase.PREPARING,
            RuntimeTransferPhase.READY,
            runtime_id=runtime_id,
            generation=desired_generation,
            object=object,
        )

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
    ) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            record = self._active(
                transfer_id,
                attempt_id,
                expected_revision,
                RuntimeTransferPhase.READY,
                now,
                runtime_id=runtime_id,
                desired_generation=desired_generation,
            )
            if (
                record is None
                or record.dispatch_status
                not in {
                    RuntimeTransferDispatchStatus.DELIVERABLE,
                    RuntimeTransferDispatchStatus.ENQUEUED,
                }
                or record.accepted_runner_generation != accepted_runner_generation
                or not phase_transition_allowed(
                    record.admission.direction,
                    record.phase,
                    RuntimeTransferPhase.STREAMING,
                )
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    phase=RuntimeTransferPhase.STREAMING,
                    revision=record.revision + 1,
                    updated_at=now,
                    dispatch_status=RuntimeTransferDispatchStatus.ENQUEUED,
                    stream_claim_id=claim_id,
                    stream_owner_replica_id=owner_replica_id,
                    stream_lease_expires_at=now + self.config.stream_lease,
                )
            )

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
    ) -> RuntimeTransferRecord | None:
        """Bind one stable dispatch identity and accepted Runner generation."""
        now = self._now()
        async with self.lock:
            self._expire(now)
            record = self._exact(transfer_id, attempt_id)
            if (
                record is None
                or self.current_attempts.get(transfer_id) != attempt_id
                or record.admission.runtime_id != runtime_id
                or record.admission.desired_generation != desired_generation
                or record.lease_expires_at <= now
                or record.logical_expires_at <= now
                or record.cancellation_requested_at is not None
                or record.phase is RuntimeTransferPhase.TERMINAL
            ):
                return None
            if record.dispatch_status is not RuntimeTransferDispatchStatus.NOT_BOUND:
                return (
                    record
                    if expected_revision <= record.revision
                    and record.dispatch_id == dispatch_id
                    and record.dispatch_request_id == dispatch_request_id
                    and record.accepted_runner_generation == accepted_runner_generation
                    else None
                )
            if (
                record.phase is not RuntimeTransferPhase.READY
                or record.revision != expected_revision
                or accepted_runner_generation <= 0
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    accepted_runner_generation=accepted_runner_generation,
                    dispatch_id=dispatch_id,
                    dispatch_status=RuntimeTransferDispatchStatus.BOUND,
                    dispatch_request_id=dispatch_request_id,
                )
            )

    async def mark_dispatch_deliverable(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        dispatch_id: str,
        dispatch_request_id: str,
    ) -> RuntimeTransferRecord | None:
        """Persist the authorization barrier before intent append."""
        now = self._now()
        async with self.lock:
            self._expire(now)
            record = self._exact(transfer_id, attempt_id)
            if (
                record is None
                or self.current_attempts.get(transfer_id) != attempt_id
                or record.dispatch_id != dispatch_id
                or record.dispatch_request_id != dispatch_request_id
                or record.phase is RuntimeTransferPhase.TERMINAL
            ):
                return None
            if record.dispatch_status in {
                RuntimeTransferDispatchStatus.DELIVERABLE,
                RuntimeTransferDispatchStatus.ENQUEUED,
            }:
                return record if expected_revision <= record.revision else None
            if (
                record.dispatch_status is not RuntimeTransferDispatchStatus.BOUND
                or record.revision != expected_revision
                or record.phase is not RuntimeTransferPhase.READY
                or record.cancellation_requested_at is not None
                or record.lease_expires_at <= now
                or record.logical_expires_at <= now
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    dispatch_status=RuntimeTransferDispatchStatus.DELIVERABLE,
                )
            )

    async def mark_dispatch_enqueued(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        operation_id: str,
        expected_revision: int,
        dispatch_id: str,
    ) -> RuntimeTransferRecord | None:
        """Record a duplicate-safe successful logical intent append."""
        now = self._now()
        async with self.lock:
            self._expire(now)
            record = self._exact(transfer_id, attempt_id)
            if (
                record is None
                or record.admission.operation_id != operation_id
                or record.dispatch_id != dispatch_id
            ):
                return None
            if record.dispatch_status is RuntimeTransferDispatchStatus.ENQUEUED:
                return record if expected_revision <= record.revision else None
            if (
                self.current_attempts.get(transfer_id) != attempt_id
                or record.dispatch_status
                is not RuntimeTransferDispatchStatus.DELIVERABLE
                or record.phase is not RuntimeTransferPhase.READY
                or record.revision != expected_revision
                or record.cancellation_requested_at is not None
                or record.lease_expires_at <= now
                or record.logical_expires_at <= now
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    dispatch_status=RuntimeTransferDispatchStatus.ENQUEUED,
                )
            )

    async def list_pending_dispatches(
        self, *, cursor: str | None, limit: int
    ) -> RuntimeTransferPage:
        """List live bound work that still needs delivery repair."""
        return await self._list_records(
            cursor=cursor,
            limit=limit,
            selected=lambda record: (
                record.phase is not RuntimeTransferPhase.TERMINAL
                and record.dispatch_status
                in {
                    RuntimeTransferDispatchStatus.BOUND,
                    RuntimeTransferDispatchStatus.DELIVERABLE,
                }
            ),
        )

    async def list_generation_dispatches(
        self, *, cursor: str | None, limit: int
    ) -> RuntimeTransferPage:
        """List all live generation-bound dispatches for repair."""
        return await self._list_records(
            cursor=cursor,
            limit=limit,
            selected=lambda record: (
                record.phase is not RuntimeTransferPhase.TERMINAL
                and record.dispatch_status
                is not RuntimeTransferDispatchStatus.NOT_BOUND
            ),
        )

    async def renew_stream_lease(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        accepted_runner_generation: int,
        expected_revision: int,
        claim_id: str,
        owner_replica_id: str,
    ) -> RuntimeTransferRecord | None:
        """Renew one owner-fenced short stream lease."""
        now = self._now()
        async with self.lock:
            record = self._active(
                transfer_id,
                attempt_id,
                expected_revision,
                RuntimeTransferPhase.STREAMING,
                now,
                accepted_runner_generation=accepted_runner_generation,
                claim_id=claim_id,
            )
            if (
                record is None
                or record.stream_owner_replica_id != owner_replica_id
                or record.stream_lease_expires_at is None
                or record.stream_lease_expires_at <= now
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    stream_lease_expires_at=now + self.config.stream_lease,
                )
            )

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
    ) -> RuntimeTransferRecord | None:
        """Persist bounded upload-abort evidence before the first multipart part."""
        now = self._now()
        async with self.lock:
            record = self._active(
                transfer_id,
                attempt_id,
                expected_revision,
                RuntimeTransferPhase.STREAMING,
                now,
                accepted_runner_generation=accepted_runner_generation,
                claim_id=claim_id,
            )
            if (
                record is None
                or record.admission.direction is not RuntimeTransferDirection.UPLOAD
                or record.stream_owner_replica_id != owner_replica_id
            ):
                return None
            if record.multipart_cleanup_handle is not None:
                return (
                    record
                    if record.multipart_cleanup_handle == cleanup_handle
                    and expected_revision <= record.revision
                    else None
                )
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    multipart_cleanup_handle=cleanup_handle,
                )
            )

    async def list_stale_stream_claims(
        self, *, cursor: str | None, limit: int
    ) -> RuntimeTransferPage:
        """List expired owner leases without automatically settling their attempts."""
        now = self._now()
        return await self._list_records(
            cursor=cursor,
            limit=limit,
            selected=lambda record: (
                record.phase is not RuntimeTransferPhase.TERMINAL
                and record.stream_lease_expires_at is not None
                and record.stream_lease_expires_at <= now
            ),
        )

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
    ) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            record = self._active(
                transfer_id,
                attempt_id,
                expected_revision,
                RuntimeTransferPhase.STREAMING,
                now,
                runtime_id=runtime_id,
                desired_generation=desired_generation,
                accepted_runner_generation=accepted_runner_generation,
                claim_id=claim_id,
            )
            if (
                record is None
                or bytes_transferred > record.admission.expected_size
                or (
                    record.progress
                    and bytes_transferred < record.progress.bytes_transferred
                )
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    progress=RuntimeTransferProgress(bytes_transferred, now),
                )
            )

    async def request_cancellation(
        self, transfer_id: str, *, attempt_id: str, expected_revision: int
    ) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            self._expire(now)
            record = self._exact(transfer_id, attempt_id)
            if record is None:
                return None
            if record.cancellation_requested_at is not None:
                return record if expected_revision <= record.revision else None
            if record.revision != expected_revision:
                return None
            if record.phase is RuntimeTransferPhase.TERMINAL:
                return record
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    cancellation_requested_at=now,
                )
            )

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
    ) -> RuntimeTransferRecord | None:
        return await self._move(
            transfer_id,
            attempt_id,
            expected_revision,
            RuntimeTransferPhase.STREAMING,
            RuntimeTransferPhase.VERIFYING,
            runtime_id=runtime_id,
            generation=desired_generation,
            required_runner_generation=accepted_runner_generation,
            required_claim_id=claim_id,
        )

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
    ) -> RuntimeTransferRecord | None:
        return await self._complete_phase(
            transfer_id,
            attempt_id,
            expected_revision,
            RuntimeTransferPhase.AVAILABLE,
            actual_size,
            actual_sha256,
            runtime_id,
            desired_generation,
            accepted_runner_generation,
            claim_id,
        )

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
    ) -> RuntimeTransferRecord | None:
        return await self._complete_phase(
            transfer_id,
            attempt_id,
            expected_revision,
            RuntimeTransferPhase.COMMITTED,
            actual_size,
            actual_sha256,
            runtime_id,
            desired_generation,
            accepted_runner_generation,
            claim_id,
        )

    async def claim_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            record = self._active(
                transfer_id,
                attempt_id,
                expected_revision,
                RuntimeTransferPhase.AVAILABLE,
                now,
            )
            if record is None or record.consumer_claim_id is not None:
                return None
            moved = dataclasses.replace(
                record,
                phase=RuntimeTransferPhase.CONSUMING,
                revision=record.revision + 1,
                updated_at=now,
                consumer_claim_id=claim_id,
                consumer_lease_expires_at=now + self.config.consumer_lease,
            )
            return self._put(moved)

    async def acknowledge_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            record = self._active(
                transfer_id,
                attempt_id,
                expected_revision,
                RuntimeTransferPhase.CONSUMING,
                now,
            )
            if record is None or record.consumer_claim_id != claim_id:
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    phase=RuntimeTransferPhase.CONSUMED,
                    revision=record.revision + 1,
                    updated_at=now,
                    consumer_acknowledged_at=now,
                    consumer_lease_expires_at=None,
                )
            )

    async def abandon_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            record = self._active(
                transfer_id,
                attempt_id,
                expected_revision,
                RuntimeTransferPhase.CONSUMING,
                now,
            )
            if record is None or record.consumer_claim_id != claim_id:
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    phase=RuntimeTransferPhase.AVAILABLE,
                    revision=record.revision + 1,
                    updated_at=now,
                    consumer_claim_id=None,
                    consumer_lease_expires_at=None,
                )
            )

    async def settle(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        outcome: RuntimeTransferOutcome,
        failure: RuntimeTransferFailure | None,
    ) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            self._expire(now)
            record = self._exact(transfer_id, attempt_id)
            if record is None:
                return None
            if record.phase is RuntimeTransferPhase.TERMINAL:
                return (
                    record
                    if expected_revision <= record.revision
                    and record.terminal_outcome is outcome
                    and record.failure is failure
                    else None
                )
            if record.revision != expected_revision:
                return None
            if (
                record.cancellation_requested_at is not None
                and outcome is RuntimeTransferOutcome.SUCCEEDED
            ):
                return None
            if outcome is RuntimeTransferOutcome.SUCCEEDED and (
                self.current_attempts.get(transfer_id) != attempt_id
                or (transfer_id, attempt_id) in self.released
                or record.lease_expires_at <= now
                or record.logical_expires_at <= now
                or (
                    record.admission.direction is RuntimeTransferDirection.DOWNLOAD
                    and record.phase is not RuntimeTransferPhase.COMMITTED
                )
                or (
                    record.admission.direction is RuntimeTransferDirection.UPLOAD
                    and record.phase is not RuntimeTransferPhase.CONSUMED
                )
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    phase=RuntimeTransferPhase.TERMINAL,
                    revision=record.revision + 1,
                    updated_at=now,
                    terminal_outcome=outcome,
                    failure=failure,
                    terminal_expires_at=terminal_expiry(now, self.config.terminal_ttl),
                )
            )

    async def record_cleanup(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        status: RuntimeTransferCleanupStatus,
    ) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            self._expire(now)
            record = self._exact(transfer_id, attempt_id)
            if record is None:
                return None
            if record.cleanup_status is status:
                return record if expected_revision <= record.revision else None
            if record.revision != expected_revision:
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    cleanup_status=status,
                    multipart_cleanup_handle=(
                        None
                        if status is RuntimeTransferCleanupStatus.COMPLETE
                        else record.multipart_cleanup_handle
                    ),
                )
            )

    async def release_admission(
        self, transfer_id: str, *, attempt_id: str, lease_id: str
    ) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            self._expire(now)
            record = self._exact(transfer_id, attempt_id)
            if record is None or record.lease_id != lease_id:
                return None
            key = (transfer_id, attempt_id)
            if key in self.released:
                return record
            self.released.add(key)
            return record

    async def list_stale(
        self, *, cursor: str | None, limit: int
    ) -> RuntimeTransferPage:
        now = self._now()
        async with self.lock:
            self._expire(now)
            if limit <= 0 or limit > self.config.list_page_size:
                raise ValueError("invalid page limit")
            keys = sorted(
                key
                for key, record in self.records.items()
                if record.phase is RuntimeTransferPhase.TERMINAL
                or key in self.released
                or record.cleanup_status
                is not RuntimeTransferCleanupStatus.NOT_REQUIRED
            )
            start = (
                0
                if cursor is None
                else bisect_right(keys, _decode_memory_stale_cursor(cursor))
            )
            page_keys = keys[start : start + limit]
            page = tuple(self.records[key] for key in page_keys)
            next_cursor = (
                _encode_memory_stale_cursor(page_keys[-1])
                if page_keys and start + len(page_keys) < len(keys)
                else None
            )
            return RuntimeTransferPage(page, next_cursor)

    async def purge_terminal(self, *, limit: int) -> int:
        now = self._now()
        async with self.lock:
            if limit <= 0:
                raise ValueError("limit must be positive")
            removed = 0
            for key in sorted(self.records):
                record = self.records[key]
                if removed == limit:
                    break
                if (
                    record.terminal_expires_at is not None
                    and record.terminal_expires_at <= now
                ):
                    del self.records[key]
                    self.released.discard(key)
                    removed += 1
                    if self.current_attempts.get(key[0]) == key[1]:
                        self.current_attempts.pop(key[0])
            return removed

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return timezone-aware datetime")
        return now

    def _current(self, transfer_id: str) -> RuntimeTransferRecord | None:
        attempt = self.current_attempts.get(transfer_id)
        return None if attempt is None else self.records.get((transfer_id, attempt))

    def _exact(self, transfer_id: str, attempt_id: str) -> RuntimeTransferRecord | None:
        return self.records.get((transfer_id, attempt_id))

    def _active(
        self,
        transfer_id: str,
        attempt_id: str,
        revision: int,
        phase: RuntimeTransferPhase,
        now: datetime,
        *,
        runtime_id: str | None = None,
        desired_generation: int | None = None,
        accepted_runner_generation: int | None = None,
        claim_id: str | None = None,
    ) -> RuntimeTransferRecord | None:
        self._expire(now)
        record = self._exact(transfer_id, attempt_id)
        if (
            record is None
            or self.current_attempts.get(transfer_id) != attempt_id
            or record.revision != revision
            or record.phase is not phase
            or (transfer_id, attempt_id) in self.released
            or record.lease_expires_at <= now
            or record.logical_expires_at <= now
            or record.cancellation_requested_at is not None
            or (runtime_id is not None and record.admission.runtime_id != runtime_id)
            or (
                desired_generation is not None
                and record.admission.desired_generation != desired_generation
            )
            or (
                accepted_runner_generation is not None
                and record.accepted_runner_generation != accepted_runner_generation
            )
            or (claim_id is not None and record.stream_claim_id != claim_id)
        ):
            return None
        return record

    async def _move(
        self,
        transfer_id: str,
        attempt_id: str,
        revision: int,
        current: RuntimeTransferPhase,
        target: RuntimeTransferPhase,
        *,
        runtime_id: str | None = None,
        generation: int | None = None,
        object: RuntimeTransferObject | None = None,
        claim_id: str | None = None,
        accepted_runner_generation: int | None = None,
        required_runner_generation: int | None = None,
        required_claim_id: str | None = None,
    ) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            record = self._active(
                transfer_id,
                attempt_id,
                revision,
                current,
                now,
                runtime_id=runtime_id,
                desired_generation=generation,
                accepted_runner_generation=required_runner_generation,
                claim_id=required_claim_id,
            )
            if (
                record is None
                or (
                    target is RuntimeTransferPhase.READY
                    and (
                        object is None
                        or object.size != record.admission.expected_size
                        or (
                            record.admission.expected_sha256 is not None
                            and object.sha256 != record.admission.expected_sha256
                        )
                    )
                )
                or not phase_transition_allowed(
                    record.admission.direction, current, target
                )
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    phase=target,
                    revision=record.revision + 1,
                    updated_at=now,
                    object=object if object is not None else record.object,
                    stream_claim_id=claim_id
                    if claim_id is not None
                    else record.stream_claim_id,
                    accepted_runner_generation=accepted_runner_generation
                    if accepted_runner_generation is not None
                    else record.accepted_runner_generation,
                )
            )

    async def _complete_phase(
        self,
        transfer_id: str,
        attempt_id: str,
        revision: int,
        target: RuntimeTransferPhase,
        actual_size: int,
        actual_sha256: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        claim_id: str,
    ) -> RuntimeTransferRecord | None:
        now = self._now()
        async with self.lock:
            record = self._active(
                transfer_id,
                attempt_id,
                revision,
                RuntimeTransferPhase.VERIFYING,
                now,
                runtime_id=runtime_id,
                desired_generation=desired_generation,
                accepted_runner_generation=accepted_runner_generation,
                claim_id=claim_id,
            )
            if (
                record is None
                or actual_size != record.admission.expected_size
                or record.object is None
                or actual_size != record.object.size
                or actual_sha256 != record.object.sha256
                or (
                    record.admission.expected_sha256 is not None
                    and actual_sha256 != record.admission.expected_sha256
                )
                or not phase_transition_allowed(
                    record.admission.direction, record.phase, target
                )
            ):
                return None
            return self._put(
                dataclasses.replace(
                    record,
                    phase=target,
                    revision=record.revision + 1,
                    updated_at=now,
                    actual_size=actual_size,
                    actual_sha256=actual_sha256,
                    multipart_cleanup_handle=None,
                )
            )

    def _has_capacity(self, admission: RuntimeTransferAdmission) -> bool:
        active = [
            record
            for key, record in self.records.items()
            if key not in self.released
            and record.phase is not RuntimeTransferPhase.TERMINAL
        ]
        runtime = [
            record
            for record in active
            if record.admission.runtime_id == admission.runtime_id
        ]
        return (
            len(active) < self.config.deployment_attempts
            and len(runtime) < self.config.per_runtime_attempts
            and sum(item.admission.expected_size for item in active)
            + admission.expected_size
            <= self.config.deployment_bytes
            and sum(item.admission.expected_size for item in runtime)
            + admission.expected_size
            <= self.config.per_runtime_bytes
        )

    async def _list_records(
        self,
        *,
        cursor: str | None,
        limit: int,
        selected: Callable[[RuntimeTransferRecord], bool],
    ) -> RuntimeTransferPage:
        """Return one deterministic bounded page after applying expiry."""
        now = self._now()
        async with self.lock:
            self._expire(now)
            if limit <= 0 or limit > self.config.list_page_size:
                raise ValueError("invalid page limit")
            keys = sorted(
                key for key, record in self.records.items() if selected(record)
            )
            start = (
                0
                if cursor is None
                else bisect_right(keys, _decode_memory_stale_cursor(cursor))
            )
            page_keys = keys[start : start + limit]
            return RuntimeTransferPage(
                records=tuple(self.records[key] for key in page_keys),
                cursor=(
                    _encode_memory_stale_cursor(page_keys[-1])
                    if page_keys and start + len(page_keys) < len(keys)
                    else None
                ),
            )

    def _expire(self, now: datetime) -> None:
        for key, original in list(self.records.items()):
            record = original
            if (
                record.phase is RuntimeTransferPhase.TERMINAL
                and record.terminal_expires_at is not None
                and record.terminal_expires_at <= now
            ):
                del self.records[key]
                self.released.discard(key)
                if self.current_attempts.get(key[0]) == key[1]:
                    self.current_attempts.pop(key[0])
                continue
            if (
                record.phase is not RuntimeTransferPhase.TERMINAL
                and record.logical_expires_at <= now
            ):
                record = dataclasses.replace(
                    record,
                    phase=RuntimeTransferPhase.TERMINAL,
                    revision=record.revision + 1,
                    updated_at=now,
                    terminal_outcome=RuntimeTransferOutcome.EXPIRED,
                    failure=RuntimeTransferFailure.EXPIRED,
                    terminal_expires_at=terminal_expiry(now, self.config.terminal_ttl),
                )
                self.records[key] = record
                self.released.add(key)
            if (
                record.phase is RuntimeTransferPhase.CONSUMING
                and record.consumer_lease_expires_at is not None
                and record.consumer_lease_expires_at <= now
            ):
                record = dataclasses.replace(
                    record,
                    phase=RuntimeTransferPhase.AVAILABLE,
                    revision=record.revision + 1,
                    updated_at=now,
                    consumer_claim_id=None,
                    consumer_lease_expires_at=None,
                )
                self.records[key] = record
            if record.lease_expires_at <= now:
                self.released.add(key)

    def _put(self, record: RuntimeTransferRecord) -> RuntimeTransferRecord:
        self.records[(record.admission.transfer_id, record.admission.attempt_id)] = (
            record
        )
        return record


def _encode_memory_stale_cursor(key: tuple[str, str]) -> str:
    """Encode one opaque immutable in-memory stale-record cursor."""
    payload = json.dumps(key, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decode_memory_stale_cursor(cursor: str) -> tuple[str, str]:
    """Decode one opaque immutable in-memory stale-record cursor."""
    try:
        value: object = json.loads(
            base64.b64decode(
                cursor.encode("ascii"),
                altchars=b"-_",
                validate=True,
            ).decode("utf-8")
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid stale page cursor") from exc
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(item, str) for item in value)
    ):
        raise ValueError("invalid stale page cursor")
    return value[0], value[1]
