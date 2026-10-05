"""Completed database-only replay preflight and exact batch fencing."""

import dataclasses
from collections import Counter
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
    CanonicalExecutionSnapshotError,
    SessionExecutionRepository,
)
from azents.repos.session_execution.cutover_replay import (
    CutoverReplayCandidate,
    SessionCutoverReplayRepository,
)
from azents.repos.session_execution.cutover_replay_data import (
    TeamSessionCutoverPreflightBatch,
    TeamSessionCutoverReplayInvariantFailure,
    TeamSessionCutoverReplayReport,
)
from azents.repos.session_execution.data import CanonicalExecutionSnapshot


@dataclasses.dataclass
class TeamSessionCutoverReplayOperationsRepository:
    """Own replay database scopes before broker effects."""

    replay_repository: Annotated[
        SessionCutoverReplayRepository,
        Depends(SessionCutoverReplayRepository),
    ]

    canonical_execution_repository: Annotated[
        SessionExecutionRepository,
        Depends(SessionExecutionRepository),
    ]

    session_manager: Annotated[
        SessionManager[WriteSession],
        Depends(get_session_manager),
    ]

    async def fence_replay_batch(
        self,
        candidates: tuple[CutoverReplayCandidate, ...],
    ) -> None:
        """Fence stale owners and revalidate the exact batch before Redis mutation."""
        failures: Counter[str] = Counter()
        async with self.session_manager() as session:
            for candidate in candidates:
                try:
                    generation = await self.replay_repository.fence_owner_generation(
                        session,
                        session_id=candidate.session_id,
                        expected_owner_generation=candidate.owner_generation,
                    )
                except ValueError:
                    failures.update(("owner_generation_stale",))
                    continue
                current = await self.replay_repository.read_candidate(
                    session,
                    session_id=candidate.session_id,
                )
                if current is None or _candidate_work_drifted(candidate, current):
                    failures.update(("durable_work_changed",))
                    continue
                try:
                    snapshot = await (
                        self.canonical_execution_repository.load_canonical_snapshot(
                            session,
                            session_id=candidate.session_id,
                            owner_generation=generation,
                        )
                    )
                except CanonicalExecutionSnapshotError:
                    failures.update(("canonical_execution_invalid",))
                    continue
                if _snapshot_work_drifted(current, snapshot):
                    failures.update(("durable_work_changed",))
            if failures:
                await session.write_session.rollback()
            else:
                await session.write_session.commit()
        if failures:
            raise TeamSessionCutoverReplayInvariantFailure(
                invariant_failures=tuple(sorted(failures.items()))
            )

    async def preflight_batch(
        self,
        *,
        batch_size: int,
        after_session_id: str | None,
    ) -> TeamSessionCutoverPreflightBatch:
        """Read and validate one exact durable candidate batch."""
        async with self.session_manager() as session:
            batch = await self.replay_repository.read_candidate_batch(
                session,
                batch_size=batch_size,
                after_session_id=after_session_id,
            )

        failures: Counter[str] = Counter()
        valid_candidates: list[CutoverReplayCandidate] = []
        for candidate in batch.candidates:
            candidate_failures = candidate.invariant_failure_codes()
            if candidate_failures:
                failures.update(candidate_failures)
                continue
            try:
                async with self.session_manager() as session:
                    snapshot = await (
                        self.canonical_execution_repository.load_canonical_snapshot(
                            session,
                            session_id=candidate.session_id,
                            owner_generation=candidate.owner_generation,
                        )
                    )
            except CanonicalExecutionOwnerGenerationStaleError:
                failures.update(("owner_generation_stale",))
                continue
            except CanonicalExecutionSnapshotError:
                failures.update(("canonical_execution_invalid",))
                continue
            if _snapshot_work_drifted(candidate, snapshot):
                failures.update(("durable_work_changed",))
                continue
            valid_candidates.append(candidate)

        return TeamSessionCutoverPreflightBatch(
            report=_report(
                candidates=batch.candidates,
                valid_candidates=valid_candidates,
                replayed_sessions=0,
                invariant_failures=failures,
                next_session_cursor=batch.next_session_cursor,
            ),
            valid_candidates=tuple(valid_candidates),
        )


def _snapshot_work_drifted(
    candidate: CutoverReplayCandidate,
    snapshot: CanonicalExecutionSnapshot,
) -> bool:
    """Return whether canonical validation no longer observes candidate work."""
    return (
        candidate.pending_command_id
        != (
            snapshot.pending_command.id
            if snapshot.pending_command is not None
            else None
        )
        or candidate.recoverable_run_id != snapshot.recoverable_run_id
        or candidate.pending_idle_continuation_run_id
        != snapshot.pending_idle_continuation_run_id
    )


def _candidate_work_drifted(
    expected: CutoverReplayCandidate,
    current: CutoverReplayCandidate,
) -> bool:
    """Compare exact durable work while allowing only the replay generation fence."""
    return (
        dataclasses.replace(
            current,
            owner_generation=expected.owner_generation,
        )
        != expected
    )


def _report(
    *,
    candidates: tuple[CutoverReplayCandidate, ...],
    valid_candidates: list[CutoverReplayCandidate],
    replayed_sessions: int,
    invariant_failures: Counter[str],
    next_session_cursor: str | None,
) -> TeamSessionCutoverReplayReport:
    """Build a content-free report from one durable replay page."""
    return TeamSessionCutoverReplayReport(
        scanned_sessions=len(candidates),
        valid_sessions=len(valid_candidates),
        replayed_sessions=replayed_sessions,
        pending_input_sessions=sum(
            candidate.has_pending_input for candidate in candidates
        ),
        pending_command_sessions=sum(
            candidate.has_pending_command for candidate in candidates
        ),
        recoverable_run_sessions=sum(
            candidate.has_recoverable_run for candidate in candidates
        ),
        pending_idle_continuation_sessions=sum(
            candidate.has_pending_idle_continuation for candidate in candidates
        ),
        stop_request_sessions=sum(
            candidate.has_stop_request for candidate in candidates
        ),
        invariant_failures=tuple(sorted(invariant_failures.items())),
        next_session_cursor=next_session_cursor,
    )
