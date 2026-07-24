"""PostgreSQL-derived preflight and replay for the Team Session cutover."""

import asyncio
import dataclasses
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
    CanonicalExecutionSnapshotError,
    SessionExecutionRepository,
)
from azents.repos.session_execution.cutover_replay import (
    CutoverReplayCandidate,
    SessionCutoverReplayRepository,
)
from azents.repos.session_execution.data import CanonicalExecutionSnapshot
from azents.utils.appctx import AppContext
from azents.worker.deps import get_worker_broker, get_worker_id

SessionBrokerProvider = Callable[[], Awaitable[SessionBroker]]
_FENCE_TIMEOUT_SECONDS = 30 * 60
_BROKER_OPERATION_TIMEOUT_SECONDS = 5 * 60


def get_team_session_cutover_broker_provider(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    worker_id: Annotated[str, Depends(get_worker_id)],
) -> SessionBrokerProvider:
    """Return a lazy broker dependency so preflight performs no Redis I/O."""

    async def provide_broker() -> SessionBroker:
        return await get_worker_broker(appctx, worker_id)

    return provide_broker


@dataclasses.dataclass(frozen=True)
class TeamSessionCutoverReplayReport:
    """Content-free result of one bounded preflight or replay batch."""

    scanned_sessions: int
    valid_sessions: int
    replayed_sessions: int
    pending_input_sessions: int
    pending_command_sessions: int
    recoverable_run_sessions: int
    pending_idle_continuation_sessions: int
    stop_request_sessions: int
    invariant_failures: tuple[tuple[str, int], ...]
    next_session_cursor: str | None


@dataclasses.dataclass(frozen=True)
class TeamSessionCutoverReplayInvariantFailure(Exception):
    """A replay batch contains invalid durable execution state."""

    invariant_failures: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        Exception.__init__(self, "Team Session cutover replay preflight failed")


class TeamSessionCutoverReplayBarrierLostError(RuntimeError):
    """The replay process lost its Redis ownership-acquisition barrier."""


@dataclasses.dataclass(frozen=True)
class _PreflightBatch:
    """One validated durable batch retained for exact replay."""

    report: TeamSessionCutoverReplayReport
    valid_candidates: tuple[CutoverReplayCandidate, ...]


@dataclasses.dataclass
class TeamSessionCutoverReplayService:
    """Reconstruct Session wake-ups from durable PostgreSQL work state."""

    replay_repository: Annotated[
        SessionCutoverReplayRepository,
        Depends(SessionCutoverReplayRepository),
    ]
    canonical_execution_repository: Annotated[
        SessionExecutionRepository,
        Depends(SessionExecutionRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    broker_provider: Annotated[
        SessionBrokerProvider,
        Depends(get_team_session_cutover_broker_provider),
    ]

    async def preflight(
        self,
        *,
        batch_size: int,
        after_session_id: str | None,
    ) -> TeamSessionCutoverReplayReport:
        """Validate one bounded PostgreSQL-derived replay batch without broker I/O."""
        preflight_batch = await self._preflight_batch(
            batch_size=batch_size,
            after_session_id=after_session_id,
        )
        return preflight_batch.report

    async def replay(
        self,
        *,
        batch_size: int,
        after_session_id: str | None,
    ) -> TeamSessionCutoverReplayReport:
        """Discard broker state and emit pure wake-ups for a valid durable batch."""
        preflight_batch = await self._preflight_batch(
            batch_size=batch_size,
            after_session_id=after_session_id,
        )
        report = preflight_batch.report
        if report.invariant_failures:
            raise TeamSessionCutoverReplayInvariantFailure(
                invariant_failures=report.invariant_failures
            )

        broker = await self.broker_provider()
        session_ids = tuple(
            candidate.session_id for candidate in preflight_batch.valid_candidates
        )
        async with asyncio.timeout(_BROKER_OPERATION_TIMEOUT_SECONDS):
            barrier_token = await broker.acquire_cutover_replay_barrier(session_ids)
        try:
            async with asyncio.timeout(_FENCE_TIMEOUT_SECONDS):
                await self._fence_replay_batch(preflight_batch.valid_candidates)
            for candidate in preflight_batch.valid_candidates:
                await _renew_barrier(
                    broker=broker,
                    session_ids=session_ids,
                    token=barrier_token,
                )
                async with asyncio.timeout(_BROKER_OPERATION_TIMEOUT_SECONDS):
                    await broker.purge_session_state(candidate.session_id)
                await _renew_barrier(
                    broker=broker,
                    session_ids=session_ids,
                    token=barrier_token,
                )
                async with asyncio.timeout(_BROKER_OPERATION_TIMEOUT_SECONDS):
                    await broker.send_message(
                        SessionWakeUp(session_id=candidate.session_id)
                    )
        finally:
            async with asyncio.timeout(_BROKER_OPERATION_TIMEOUT_SECONDS):
                await broker.release_cutover_replay_barrier(
                    session_ids,
                    barrier_token,
                )

        return dataclasses.replace(
            report,
            replayed_sessions=len(preflight_batch.valid_candidates),
        )

    async def _fence_replay_batch(
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
                await session.rollback()
            else:
                await session.commit()
        if failures:
            raise TeamSessionCutoverReplayInvariantFailure(
                invariant_failures=tuple(sorted(failures.items()))
            )

    async def _preflight_batch(
        self,
        *,
        batch_size: int,
        after_session_id: str | None,
    ) -> _PreflightBatch:
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

        return _PreflightBatch(
            report=_report(
                candidates=batch.candidates,
                valid_candidates=valid_candidates,
                replayed_sessions=0,
                invariant_failures=failures,
                next_session_cursor=batch.next_session_cursor,
            ),
            valid_candidates=tuple(valid_candidates),
        )


async def _renew_barrier(
    *,
    broker: SessionBroker,
    session_ids: tuple[str, ...],
    token: str,
) -> None:
    """Renew the exact cutover barrier or abort before another operation."""
    async with asyncio.timeout(_BROKER_OPERATION_TIMEOUT_SECONDS):
        renewed = await broker.renew_cutover_replay_barrier(
            session_ids,
            token,
        )
    if not renewed:
        raise TeamSessionCutoverReplayBarrierLostError(
            "Team Session cutover replay barrier was lost"
        )


def _snapshot_work_drifted(
    candidate: CutoverReplayCandidate,
    snapshot: CanonicalExecutionSnapshot,
) -> bool:
    """Return whether canonical validation no longer observes candidate work."""
    return (
        candidate.fifo_input_buffer_id != snapshot.fifo_input_buffer_id
        or candidate.pending_command_id
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
