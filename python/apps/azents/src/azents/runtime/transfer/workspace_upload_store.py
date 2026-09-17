"""Workspace upload volatile metadata-store contract."""

from typing import Protocol

from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadAdmission,
    WorkspaceUploadDeliveryAttempt,
    WorkspaceUploadDeliveryOutcome,
    WorkspaceUploadDestinationEvidence,
    WorkspaceUploadFailure,
    WorkspaceUploadPage,
    WorkspaceUploadRecord,
)
from azents.runtime.transfer.workspace_upload_object import (
    WorkspaceUploadObjectHandles,
)


class WorkspaceUploadStore(Protocol):
    """Atomic requester-bound Workspace upload metadata owned by Runtime Control."""

    async def create(
        self,
        admission: WorkspaceUploadAdmission,
    ) -> WorkspaceUploadRecord | None: ...

    async def get(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
    ) -> WorkspaceUploadRecord | None: ...

    async def compare_and_set(
        self,
        record: WorkspaceUploadRecord,
        *,
        expected_revision: int,
    ) -> WorkspaceUploadRecord | None: ...

    async def claim_ingress(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> WorkspaceUploadRecord | None: ...

    async def renew_ingress_lease(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> WorkspaceUploadRecord | None: ...

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
    ) -> WorkspaceUploadRecord | None: ...

    async def append_delivery_attempt(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        attempt: WorkspaceUploadDeliveryAttempt,
    ) -> WorkspaceUploadRecord | None: ...

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
    ) -> WorkspaceUploadRecord | None: ...

    async def request_cancellation(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        current_delivery_number: int | None = None,
    ) -> WorkspaceUploadRecord | None: ...

    async def claim_reconciliation(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> WorkspaceUploadRecord | None: ...

    async def claim_cleanup(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> WorkspaceUploadRecord | None: ...

    async def list_reconciliation(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> WorkspaceUploadPage: ...

    async def list_cleanup(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> WorkspaceUploadPage: ...

    async def list_object_handles(self) -> WorkspaceUploadObjectHandles: ...

    async def purge_terminal(self, *, limit: int) -> int: ...
