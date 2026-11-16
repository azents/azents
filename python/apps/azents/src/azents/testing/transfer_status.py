"""Complete coordinator projections for narrow source-cleanup test doubles."""

import datetime
import hashlib

from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorCleanupStatus,
    CoordinatorDispatchStatus,
    CoordinatorExpectedManifest,
    CoordinatorPreparationCleanupState,
    CoordinatorTransferPhase,
    CoordinatorTransferStatus,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity


def preparation_status(
    identity: CoordinatorTransferIdentity, revision: int
) -> CoordinatorTransferStatus:
    """Build the actual status contract, including fields irrelevant to cleanup."""
    deadline = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
    return CoordinatorTransferStatus(
        identity=identity,
        phase=CoordinatorTransferPhase.PREPARING,
        revision=revision,
        accepted_runner_generation=None,
        dispatch_id=None,
        dispatch_status=CoordinatorDispatchStatus.NOT_BOUND,
        expected_manifest=CoordinatorExpectedManifest(
            size=0, sha256=hashlib.sha256(b"").hexdigest()
        ),
        actual_manifest=None,
        deadline_at=deadline,
        logical_expires_at=deadline,
        outcome=None,
        failure=None,
        cleanup_status=CoordinatorCleanupStatus.NOT_REQUIRED,
        cancellation_requested=False,
        preparation_cleanup_state=CoordinatorPreparationCleanupState.NOT_REQUIRED,
        destination_conflict=None,
    )
