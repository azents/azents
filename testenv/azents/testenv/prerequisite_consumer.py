"""Prerequisite snapshot consumer helpers."""

import datetime as dt
from pathlib import Path

from testenv.fixture_worktree import current_worktree_fingerprint
from testenv.prerequisite_contracts import load_all_contracts
from testenv.prerequisite_errors import PrerequisiteError, PrerequisiteErrorDetail
from testenv.prerequisite_prepare import contract_hash
from testenv.prerequisite_snapshot import (
    PrerequisiteSnapshot,
    PrerequisiteSnapshotEntry,
    load_prerequisite_snapshot,
)


def require_ready_prerequisite(
    contract_id: str,
    *,
    profile: str,
    testenv_root: Path,
    now: dt.datetime | None = None,
) -> PrerequisiteSnapshotEntry:
    """Require a ready prerequisite snapshot entry before a test run."""
    snapshot = load_prerequisite_snapshot(profile, testenv_root)
    _validate_snapshot_freshness(snapshot, testenv_root, now=now)
    for entry in snapshot.entries:
        if entry.contract_id != contract_id:
            continue
        if entry.status == "ready":
            return entry
        raise PrerequisiteError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_NOT_READY",
                message=f"Prerequisite contract is not ready: {contract_id}",
                contract_id=contract_id,
                profile=profile,
            )
        )
    raise PrerequisiteError(
        PrerequisiteErrorDetail(
            code="PREREQUISITE_CONTRACT_NOT_IN_SNAPSHOT",
            message=f"Prerequisite contract is missing from snapshot: {contract_id}",
            contract_id=contract_id,
            profile=profile,
        )
    )


def _validate_snapshot_freshness(
    snapshot: PrerequisiteSnapshot,
    testenv_root: Path,
    *,
    now: dt.datetime | None,
) -> None:
    """Validate snapshot TTL, contract hash, and worktree fingerprint."""
    current_time = now or dt.datetime.now(dt.UTC)
    if snapshot.is_stale(current_time):
        raise PrerequisiteError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_SNAPSHOT_STALE",
                message="Prerequisite snapshot is stale; run prerequisite prepare again",
                profile=snapshot.profile,
            )
        )

    expected_contract_hash = contract_hash(load_all_contracts(testenv_root))
    if snapshot.contract_hash != expected_contract_hash:
        raise PrerequisiteError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_CONTRACT_HASH_STALE",
                message="Prerequisite contract hash changed; run prerequisite prepare again",
                profile=snapshot.profile,
            )
        )

    current_worktree = current_worktree_fingerprint(testenv_root)
    if snapshot.worktree.fingerprint != current_worktree.fingerprint:
        raise PrerequisiteError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_WORKTREE_STALE",
                message="Prerequisite snapshot was generated for a different worktree state",
                profile=snapshot.profile,
            )
        )
