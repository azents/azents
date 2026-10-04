"""Expired ownership can settle metadata but never revive private work authority."""

import asyncio
import dataclasses
import datetime
from typing import NamedTuple
from unittest.mock import Mock

import pytest
import sqlalchemy as sa

import azents.services.historical_memory.consolidation_job as jobs
from azents.core.historical_memory_consolidation import (
    ConsolidationAttemptState,
    ConsolidationUnitKey,
)
from azents.core.historical_memory_system_setting import HistoricalMemoryExecutionConfig
from azents.engine.model_stream import AsyncioModelStreamClock
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
    database_now,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationClaim,
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.publication import (
    ConsolidationPublicationOutcome,
    ConsolidationPublicationRepository,
)
from azents.services.historical_memory.consolidation_job import (
    HistoricalMemoryConsolidationService,
)
from azents.testing.consolidated_context import publish_context_overview
from azents.testing.consolidation import (
    consolidation_deadline,
    create_consolidation_source,
    seed_consolidation_corpus,
)


@dataclasses.dataclass(frozen=True)
class _State:
    state: ConsolidationAttemptState
    finished_at: datetime.datetime | None
    failure_code: str | None
    active_attempt_id: str | None
    token: str | None
    generation: int
    lease: datetime.datetime | None
    failure_count: int
    no_progress_count: int
    retry_at: datetime.datetime | None
    published_revision_id: str | None
    work_states: tuple[tuple[str, str], ...]


class _PublishedUnit(NamedTuple):
    key: ConsolidationUnitKey
    revision_id: str


async def _state(
    manager: SessionManager[WriteSession], claim: ConsolidationClaim
) -> _State:
    async with manager() as session:
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, claim.principal.attempt_id
        )
        unit = await session.read_session.get(RDBConsolidationUnit, claim.unit_id)
        assert attempt is not None and unit is not None
        work = await session.read_session.execute(
            sa.select(RDBConsolidationWork.id, RDBConsolidationWork.state)
            .where(RDBConsolidationWork.agent_id == claim.principal.unit.agent_id)
            .order_by(RDBConsolidationWork.id)
        )
        return _State(
            attempt.state,
            attempt.finished_at,
            attempt.failure_code,
            unit.active_attempt_id,
            unit.owner_token,
            unit.owner_generation,
            unit.lease_until,
            unit.failure_count,
            unit.no_progress_count,
            unit.retry_at,
            unit.published_revision_id,
            tuple((row.id, row.state.value) for row in work),
        )


async def _published_unit(manager: SessionManager[WriteSession]) -> _PublishedUnit:
    corpus = await seed_consolidation_corpus(manager)
    revision = await publish_context_overview(
        manager,
        key=corpus.team,
        markdown="## Historical Context\nPrior completed context.\n\n## Source Routes\n"
        f"- azents://memory/historical/team/{corpus.team_source}/summary.md — Source\n",
    )
    async with manager() as session:
        await create_consolidation_source(
            session,
            manager=manager,
            key=corpus.team,
            summary="New pending context",
            title="Pending source",
        )
    return _PublishedUnit(corpus.team, revision)


@dataclasses.dataclass
class _PausedAttempt:
    claim: ConsolidationClaim
    ownership_repository: ConsolidationOwnershipRepository
    publication_repository: ConsolidationPublicationRepository
    started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    stopped: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    closed: bool = False

    async def run(self) -> ConsolidationPublicationOutcome:
        self.started.set()
        try:
            await asyncio.Event().wait()
            raise AssertionError("A paused execution must be cancelled")
        finally:
            self.stopped.set()

    async def close(self) -> None:
        assert self.stopped.is_set()
        self.closed = True


def _service(
    manager: SessionManager[WriteSession],
) -> HistoricalMemoryConsolidationService:
    return HistoricalMemoryConsolidationService(
        session_manager=manager,
        config=Mock(),
        agent_repository=Mock(),
        health_repository=Mock(),
        active_capabilities_repository=Mock(),
        model_read_repository=Mock(),
        metadata_service=Mock(),
        runtime_token_resolver=Mock(),
        sdk_factories=Mock(),
        watchdog=Mock(clock=AsyncioModelStreamClock()),
        read_session_manager=manager,
    )


@pytest.mark.parametrize("runtime_first", [False, True])
async def test_true_deadline_settles_after_supervision_quiesces(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    runtime_first: bool,
) -> None:
    """Supervisor timeout and the outer Runtime cutoff preserve prior publication."""
    manager = rdb_session_manager
    key, prior_revision = await _published_unit(manager)
    instances: list[_PausedAttempt] = []
    before: list[_State] = []
    ready = asyncio.Event()

    def attempt_factory(
        service: HistoricalMemoryConsolidationService,
        claim: ConsolidationClaim,
        ownership: ConsolidationOwnershipRepository,
        publication: ConsolidationPublicationRepository,
        policy: HistoricalMemoryExecutionConfig,
    ) -> _PausedAttempt:
        attempt = _PausedAttempt(claim, ownership, publication)
        instances.append(attempt)
        ready.set()
        return attempt

    monkeypatch.setattr(jobs, "ConsolidationAttemptExecution", attempt_factory)
    service = _service(manager)
    deadline = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=0.5)
    cutoff = asyncio.timeout_at(
        asyncio.get_running_loop().time()
        + (deadline - datetime.datetime.now(datetime.UTC)).total_seconds()
    )

    async def execute() -> None:
        if runtime_first:
            async with cutoff:
                await service.run_unit(
                    key,
                    execution_policy=HistoricalMemoryExecutionConfig(timeout_seconds=1),
                    deadline=deadline,
                )
        else:
            await service.run_unit(
                key,
                execution_policy=HistoricalMemoryExecutionConfig(timeout_seconds=1),
                deadline=deadline,
            )

    task = asyncio.create_task(execute())
    await asyncio.wait_for(ready.wait(), timeout=2)
    await instances[0].started.wait()
    before.append(await _state(manager, instances[0].claim))
    with pytest.raises(TimeoutError):
        await task
    attempt = instances[0]
    assert attempt.stopped.is_set() and attempt.closed
    if runtime_first:
        assert cutoff.expired(), "Outer Runtime timer must be the cancellation origin"
    after = await _state(manager, attempt.claim)
    assert after.state is ConsolidationAttemptState.FAILED
    assert after.finished_at is not None and after.finished_at >= deadline
    assert after.failure_code is None
    assert (
        after.active_attempt_id is None and after.token is None and after.lease is None
    )
    assert after.failure_count == before[0].failure_count + 1
    assert after.no_progress_count == before[0].no_progress_count + 1
    assert after.retry_at == after.finished_at + datetime.timedelta(seconds=60)
    assert after.published_revision_id == prior_revision
    assert after.work_states == before[0].work_states
    with pytest.raises(ConsolidationAuthorityError):
        await ConsolidationDraftRepository(manager).observe(
            attempt.claim.principal, path="summary.md"
        )


async def test_external_cancellation_before_deadline_keeps_recovery_semantics(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    ready = asyncio.Event()
    attempts: list[_PausedAttempt] = []

    def factory(
        service: HistoricalMemoryConsolidationService,
        claim: ConsolidationClaim,
        ownership: ConsolidationOwnershipRepository,
        publication: ConsolidationPublicationRepository,
        policy: HistoricalMemoryExecutionConfig,
    ) -> _PausedAttempt:
        attempt = _PausedAttempt(claim, ownership, publication)
        attempts.append(attempt)
        ready.set()
        return attempt

    monkeypatch.setattr(jobs, "ConsolidationAttemptExecution", factory)
    task = asyncio.create_task(
        _service(manager).run_unit(
            corpus.team,
            execution_policy=HistoricalMemoryExecutionConfig(),
            deadline=consolidation_deadline(),
        )
    )
    await ready.wait()
    await attempts[0].started.wait()
    before = await _state(manager, attempts[0].claim)
    task.cancel("external-shutdown")
    with pytest.raises(asyncio.CancelledError, match="external-shutdown"):
        await task
    assert attempts[0].closed and attempts[0].stopped.is_set()
    assert await _state(manager, attempts[0].claim) == before


async def test_elapsed_lease_and_deadline_allow_only_exact_metadata_settlement(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    key, prior_revision = await _published_unit(manager)
    ownership = ConsolidationOwnershipRepository(manager)
    claim = await ownership.claim(key, deadline=consolidation_deadline())
    assert claim is not None
    async with manager() as session:
        unit = await session.write_session.get(RDBConsolidationUnit, claim.unit_id)
        attempt = await session.write_session.get(
            RDBConsolidationAttempt, claim.principal.attempt_id
        )
        assert unit is not None and attempt is not None
        now = await database_now(session)
        unit.lease_until = now - datetime.timedelta(seconds=1)
        attempt.deadline_at = now - datetime.timedelta(seconds=1)
        unit.failure_count = 2
        unit.no_progress_count = 2
    before = await _state(manager, claim)
    with pytest.raises(ConsolidationAuthorityError):
        await ownership.validate(claim.principal)
    await ownership.fail(claim.principal, failure_code=None, cancelled=False)
    after = await _state(manager, claim)
    assert after.state is ConsolidationAttemptState.FAILED
    assert after.finished_at is not None
    assert after.failure_code is None and after.active_attempt_id is None
    assert after.token is None and after.lease is None
    assert after.failure_count == 3 and after.no_progress_count == 3
    assert after.retry_at == after.finished_at + datetime.timedelta(seconds=240)
    assert after.published_revision_id == prior_revision
    assert after.work_states == before.work_states


@pytest.mark.parametrize(
    "mismatch",
    [
        "token",
        "generation",
        "attempt",
        "identity",
        "attempt_owner",
        "attempt_unit",
        "completed",
    ],
)
async def test_terminal_settlement_rejects_stale_or_completed_principal_without_changes(
    rdb_session_manager: SessionManager[WriteSession],
    mismatch: str,
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    ownership = ConsolidationOwnershipRepository(manager)
    claim = await ownership.claim(corpus.team, deadline=consolidation_deadline())
    assert claim is not None
    principal = claim.principal
    match mismatch:
        case "token":
            principal = principal.model_copy(update={"owner_token": "x" * 32})
        case "generation":
            principal = principal.model_copy(
                update={"owner_generation": principal.owner_generation + 1}
            )
        case "attempt":
            principal = principal.model_copy(update={"attempt_id": "x" * 32})
        case "identity":
            principal = principal.model_copy(update={"unit": corpus.personal})
        case "attempt_owner":
            async with manager() as session:
                attempt = await session.write_session.get(
                    RDBConsolidationAttempt, principal.attempt_id
                )
                assert attempt is not None
                attempt.owner_token = "x" * 32
        case "attempt_unit":
            peer = await ownership.claim(
                corpus.personal, deadline=consolidation_deadline()
            )
            assert peer is not None
            async with manager() as session:
                attempt = await session.write_session.get(
                    RDBConsolidationAttempt, principal.attempt_id
                )
                assert attempt is not None
                attempt.unit_id = peer.unit_id
        case "completed":
            async with manager() as session:
                attempt = await session.write_session.get(
                    RDBConsolidationAttempt, principal.attempt_id
                )
                assert attempt is not None
                attempt.state = ConsolidationAttemptState.COMPLETED
                attempt.finished_at = await database_now(session)
    before = await _state(manager, claim)
    with pytest.raises(ConsolidationAuthorityError):
        await ownership.fail(principal, failure_code=None, cancelled=False)
    assert await _state(manager, claim) == before


async def test_reclaimed_unit_cannot_be_settled_by_previous_owner(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    ownership = ConsolidationOwnershipRepository(manager)
    old = await ownership.claim(corpus.team, deadline=consolidation_deadline())
    assert old is not None
    async with manager() as session:
        unit = await session.write_session.get(RDBConsolidationUnit, old.unit_id)
        assert unit is not None
        unit.lease_until = await database_now(session) - datetime.timedelta(seconds=1)
    current = await ownership.claim(corpus.team, deadline=consolidation_deadline())
    assert current is not None
    before_old = await _state(manager, old)
    before_current = await _state(manager, current)
    with pytest.raises(ConsolidationAuthorityError):
        await ownership.fail(old.principal, failure_code=None, cancelled=False)
    assert await _state(manager, old) == before_old
    assert await _state(manager, current) == before_current
