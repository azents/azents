"""Runtime Control coordination for direct-object Workspace uploads."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

from azcommon.uuid import uuid7

from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadAdmission,
    WorkspaceUploadCleanupArtifact,
    WorkspaceUploadCleanupFailureEvidence,
    WorkspaceUploadCleanupStatus,
    WorkspaceUploadDeliveryAttempt,
    WorkspaceUploadFailure,
    WorkspaceUploadOutcome,
    WorkspaceUploadPage,
    WorkspaceUploadPhase,
    WorkspaceUploadRecord,
    workspace_upload_terminal_expiry,
)
from azents.runtime.transfer.workspace_upload_object import (
    WorkspaceUploadObjectStore,
    WorkspaceUploadUploadTicket,
)
from azents.runtime.transfer.workspace_upload_store import WorkspaceUploadStore


class WorkspaceUploadReconciliationHandler(Protocol):
    """Advance one finalized upload through Runtime delivery."""

    async def reconcile(self, record: WorkspaceUploadRecord) -> None:
        """Reconcile one record after this coordinator holds its lease."""
        ...


@dataclass(frozen=True)
class WorkspaceUploadReconcileResult:
    """Bounded evidence from one Workspace upload reconcile pass."""

    reconciliation_page: WorkspaceUploadPage
    cleanup_page: WorkspaceUploadPage
    reconciled: int
    cleaned: int
    cleanup_failures: int
    purged_terminal: int


class WorkspaceUploadCoordinator:
    """Coordinate metadata, direct-object finalization, delivery, and cleanup."""

    def __init__(
        self,
        *,
        store: WorkspaceUploadStore,
        object_store: WorkspaceUploadObjectStore,
        reconciliation_handler: WorkspaceUploadReconciliationHandler,
        ingress_handle_factory: Callable[[], str],
        source_handle_factory: Callable[[], str],
        claim_id_factory: Callable[[], str],
        clock: Callable[[], datetime],
        terminal_ttl: timedelta,
        delivery_attempt_id_factory: Callable[[], str] | None = None,
        transfer_id_factory: Callable[[], str] | None = None,
        transfer_attempt_id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Initialize direct-object upload coordination dependencies."""
        if terminal_ttl <= timedelta():
            raise ValueError("Workspace upload terminal retention must be positive")
        self.store = store
        self.object_store = object_store
        self.reconciliation_handler = reconciliation_handler
        self.ingress_handle_factory = ingress_handle_factory
        self.source_handle_factory = source_handle_factory
        self.claim_id_factory = claim_id_factory
        self.clock = clock
        self.terminal_ttl = terminal_ttl
        self.delivery_attempt_id_factory = delivery_attempt_id_factory or (
            lambda: uuid7().hex
        )
        self.transfer_id_factory = transfer_id_factory or (lambda: uuid7().hex)
        self.transfer_attempt_id_factory = transfer_attempt_id_factory or (
            lambda: uuid7().hex
        )

    async def create(
        self,
        admission: WorkspaceUploadAdmission,
    ) -> WorkspaceUploadRecord | None:
        """Create one operation and allocate its opaque ingress handle."""
        record = await self.store.create(admission)
        if record is None or record.ingress_handle is not None:
            return record
        return await self.store.compare_and_set(
            replace(
                record,
                phase=WorkspaceUploadPhase.UPLOADING,
                ingress_handle=self.ingress_handle_factory(),
            ),
            expected_revision=record.revision,
        )

    async def issue_upload_ticket(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
    ) -> WorkspaceUploadUploadTicket | None:
        """Issue a one-shot browser PUT ticket without storing its URL."""
        record = await self.get(
            upload_id,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        if record is None or record.phase is not WorkspaceUploadPhase.UPLOADING:
            return None
        return await self.object_store.issue_upload_ticket(record)

    async def get(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
    ) -> WorkspaceUploadRecord | None:
        """Get one requester-authorized Workspace upload record."""
        return await self.store.get(
            upload_id,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )

    async def finalize(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
    ) -> WorkspaceUploadRecord | None:
        """Verify the direct PUT object and publish one immutable source snapshot."""
        record = await self.get(
            upload_id,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        if record is None or record.revision != expected_revision:
            return None
        if record.source_handle is not None or record.pending_source_handle is not None:
            return (
                record
                if record.phase is WorkspaceUploadPhase.MOVING_TO_RUNTIME
                else None
            )
        if (
            record.phase is not WorkspaceUploadPhase.UPLOADING
            or record.ingress_handle is None
        ):
            return None
        claimed = await self.store.claim_ingress(
            upload_id,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            expected_revision=expected_revision,
            claim_id=self.claim_id_factory(),
        )
        if claimed is None:
            return None
        source_handle = self.source_handle_factory()
        prepared = await self.store.compare_and_set(
            replace(claimed, pending_source_handle=source_handle),
            expected_revision=claimed.revision,
        )
        if prepared is None:
            return None
        try:
            evidence = await self.object_store.finalize(
                prepared,
                source_handle=source_handle,
            )
        except asyncio.CancelledError:
            raise
        except FileNotFoundError:
            await self._mark_finalize_failure(prepared, WorkspaceUploadFailure.INGRESS)
            return None
        except ValueError:
            await self._mark_finalize_failure(
                prepared,
                WorkspaceUploadFailure.INTEGRITY,
            )
            return None
        except Exception:
            await self._mark_finalize_failure(prepared, WorkspaceUploadFailure.INGRESS)
            return None
        current = await self.store.get(
            upload_id,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        if current is None or current.revision != prepared.revision:
            return None
        if current.cancellation_requested_at is not None:
            await self._mark_cancelled(current)
            return None
        return await self.store.compare_and_set(
            replace(
                current,
                phase=WorkspaceUploadPhase.MOVING_TO_RUNTIME,
                pending_source_handle=None,
                source_handle=evidence.source_handle,
                actual_size=evidence.actual_size,
                actual_sha256=evidence.actual_sha256,
                received_size=evidence.actual_size,
                ingress_claim_id=None,
                ingress_lease_expires_at=None,
                failure=None,
            ),
            expected_revision=current.revision,
        )

    async def cancel(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        current_delivery_number: int | None = None,
    ) -> WorkspaceUploadRecord | None:
        """Request idempotent cancellation of one exact upload operation."""
        return await self.store.request_cancellation(
            upload_id,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            expected_revision=expected_revision,
            current_delivery_number=current_delivery_number,
        )

    async def retry(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        current_delivery_number: int,
        overwrite: bool = False,
        conflict_precondition: str | None = None,
    ) -> WorkspaceUploadRecord | None:
        """Queue one new immutable Runtime delivery attempt."""
        record = await self.get(
            upload_id,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        if (
            record is None
            or record.revision != expected_revision
            or record.current_delivery_number != current_delivery_number
            or record.source_handle is None
            or record.phase
            not in {
                WorkspaceUploadPhase.CONFLICTED,
                WorkspaceUploadPhase.RETRYABLE_FAILURE,
            }
        ):
            return None
        if overwrite:
            if record.phase is not WorkspaceUploadPhase.CONFLICTED:
                return None
            latest = record.delivery_attempts[-1]
            if (
                latest.conflict_revision is None
                or conflict_precondition is None
                or conflict_precondition != latest.conflict_revision
            ):
                return None
        elif conflict_precondition is not None:
            return None
        attempt = WorkspaceUploadDeliveryAttempt(
            number=len(record.delivery_attempts) + 1,
            attempt_id=self.delivery_attempt_id_factory(),
            transfer_id=self.transfer_id_factory(),
            transfer_attempt_id=self.transfer_attempt_id_factory(),
            overwrite=overwrite,
            conflict_precondition=conflict_precondition,
            created_at=self.clock(),
            completed_at=None,
            outcome=None,
            failure=None,
            conflict_revision=None,
            destination_evidence=None,
        )
        return await self.store.append_delivery_attempt(
            upload_id,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            expected_revision=expected_revision,
            attempt=attempt,
        )

    async def reconcile(
        self,
        *,
        reconciliation_cursor: str | None,
        cleanup_cursor: str | None,
        limit: int,
    ) -> WorkspaceUploadReconcileResult:
        """Claim and advance bounded delivery and object cleanup pages."""
        reconciliation_page = await self.store.list_reconciliation(
            cursor=reconciliation_cursor,
            limit=limit,
        )
        reconciled = 0
        for record in reconciliation_page.records:
            claimed = await self.store.claim_reconciliation(
                record.admission.upload_id,
                requester_user_id=record.admission.requester_user_id,
                workspace_id=record.admission.workspace_id,
                agent_id=record.admission.agent_id,
                expected_revision=record.revision,
                claim_id=self.claim_id_factory(),
            )
            if claimed is None:
                continue
            await self.reconciliation_handler.reconcile(claimed)
            reconciled += 1

        cleanup_page = await self.store.list_cleanup(
            cursor=cleanup_cursor,
            limit=limit,
        )
        cleaned = 0
        cleanup_failures = 0
        for record in cleanup_page.records:
            claimed = await self.store.claim_cleanup(
                record.admission.upload_id,
                requester_user_id=record.admission.requester_user_id,
                workspace_id=record.admission.workspace_id,
                agent_id=record.admission.agent_id,
                expected_revision=record.revision,
                claim_id=self.claim_id_factory(),
            )
            if claimed is None:
                continue
            cleanup_result = await self._cleanup_claimed(claimed)
            if cleanup_result == "cleaned":
                cleaned += 1
            elif cleanup_result == "failed":
                cleanup_failures += 1

        purged_terminal = await self.store.purge_terminal(limit=limit)
        return WorkspaceUploadReconcileResult(
            reconciliation_page=reconciliation_page,
            cleanup_page=cleanup_page,
            reconciled=reconciled,
            cleaned=cleaned,
            cleanup_failures=cleanup_failures,
            purged_terminal=purged_terminal,
        )

    async def _cleanup_claimed(self, record: WorkspaceUploadRecord) -> str:
        """Delete owned source artifacts one at a time with durable progress."""
        current = record
        while True:
            if current.ingress_handle is not None:
                artifact = WorkspaceUploadCleanupArtifact.INGRESS_OBJECT_DELETE
                handle = current.ingress_handle
                delete = self.object_store.delete_ingress_object
            elif current.pending_source_handle is not None:
                artifact = WorkspaceUploadCleanupArtifact.SNAPSHOT_OBJECT_DELETE
                handle = current.pending_source_handle
                delete = self.object_store.delete_source_object
            elif current.source_handle is not None:
                artifact = WorkspaceUploadCleanupArtifact.SOURCE_OBJECT_DELETE
                handle = current.source_handle
                delete = self.object_store.delete_source_object
            else:
                break
            try:
                await delete(handle)
            except asyncio.CancelledError:
                raise
            except Exception:
                return (
                    "failed"
                    if await self._record_cleanup_failure(current, artifact) is not None
                    else "stale"
                )
            updated = await self._record_cleanup_artifact_complete(
                current,
                artifact,
            )
            if updated is None:
                return "stale"
            current = updated
        return (
            "cleaned"
            if await self._record_cleanup_complete(current) is not None
            else "stale"
        )

    async def _mark_finalize_failure(
        self,
        record: WorkspaceUploadRecord,
        failure: WorkspaceUploadFailure,
    ) -> None:
        """Project one failed direct-object finalization."""
        current = await self.store.get(
            record.admission.upload_id,
            requester_user_id=record.admission.requester_user_id,
            workspace_id=record.admission.workspace_id,
            agent_id=record.admission.agent_id,
        )
        if current is None or current.phase is not WorkspaceUploadPhase.UPLOADING:
            return
        await self.store.compare_and_set(
            replace(
                current,
                phase=WorkspaceUploadPhase.FAILED,
                ingress_claim_id=None,
                ingress_lease_expires_at=None,
                cleanup_status=(
                    WorkspaceUploadCleanupStatus.PENDING
                    if (
                        current.ingress_handle is not None
                        or current.pending_source_handle is not None
                        or current.source_handle is not None
                    )
                    else WorkspaceUploadCleanupStatus.NOT_REQUIRED
                ),
                outcome=WorkspaceUploadOutcome.FAILED,
                failure=failure,
                terminal_expires_at=workspace_upload_terminal_expiry(
                    self.clock(),
                    self.terminal_ttl,
                ),
            ),
            expected_revision=current.revision,
        )

    async def _mark_cancelled(self, record: WorkspaceUploadRecord) -> None:
        """Terminalize a cancellation observed during finalization."""
        await self.store.compare_and_set(
            replace(
                record,
                phase=WorkspaceUploadPhase.CANCELLED,
                ingress_claim_id=None,
                ingress_lease_expires_at=None,
                cleanup_status=(
                    WorkspaceUploadCleanupStatus.PENDING
                    if (
                        record.ingress_handle is not None
                        or record.pending_source_handle is not None
                        or record.source_handle is not None
                    )
                    else WorkspaceUploadCleanupStatus.NOT_REQUIRED
                ),
                outcome=WorkspaceUploadOutcome.CANCELLED,
                failure=WorkspaceUploadFailure.CANCELLED,
                terminal_expires_at=workspace_upload_terminal_expiry(
                    self.clock(),
                    self.terminal_ttl,
                ),
            ),
            expected_revision=record.revision,
        )

    async def _record_cleanup_complete(
        self,
        record: WorkspaceUploadRecord,
    ) -> WorkspaceUploadRecord | None:
        """CAS-settle successfully deleted object artifacts."""
        return await self.store.compare_and_set(
            replace(
                record,
                cleanup_claim_id=None,
                cleanup_lease_expires_at=None,
                cleanup_status=WorkspaceUploadCleanupStatus.COMPLETE,
                cleanup_failure=None,
            ),
            expected_revision=record.revision,
        )

    async def _record_cleanup_artifact_complete(
        self,
        record: WorkspaceUploadRecord,
        artifact: WorkspaceUploadCleanupArtifact,
    ) -> WorkspaceUploadRecord | None:
        """CAS-clear exactly one successfully deleted artifact handle."""
        if artifact is WorkspaceUploadCleanupArtifact.INGRESS_OBJECT_DELETE:
            updated = replace(record, ingress_handle=None, cleanup_failure=None)
        elif artifact is WorkspaceUploadCleanupArtifact.SNAPSHOT_OBJECT_DELETE:
            updated = replace(
                record,
                pending_source_handle=None,
                cleanup_failure=None,
            )
        elif artifact is WorkspaceUploadCleanupArtifact.SOURCE_OBJECT_DELETE:
            updated = replace(
                record,
                source_handle=None,
                actual_size=None,
                actual_sha256=None,
                cleanup_failure=None,
            )
        else:
            raise ValueError(
                f"Unsupported Workspace upload cleanup artifact: {artifact}"
            )
        return await self.store.compare_and_set(
            updated,
            expected_revision=record.revision,
        )

    async def _record_cleanup_failure(
        self,
        record: WorkspaceUploadRecord,
        artifact: WorkspaceUploadCleanupArtifact,
    ) -> WorkspaceUploadRecord | None:
        """CAS-record bounded retryable object-cleanup evidence."""
        previous = record.cleanup_failure
        attempts = (
            1
            if previous is None or previous.artifact is not artifact
            else previous.attempts + 1
        )
        return await self.store.compare_and_set(
            replace(
                record,
                cleanup_claim_id=None,
                cleanup_lease_expires_at=None,
                cleanup_status=WorkspaceUploadCleanupStatus.RETRYABLE_FAILURE,
                cleanup_failure=WorkspaceUploadCleanupFailureEvidence(
                    artifact=artifact,
                    observed_at=self.clock(),
                    attempts=attempts,
                ),
            ),
            expected_revision=record.revision,
        )
