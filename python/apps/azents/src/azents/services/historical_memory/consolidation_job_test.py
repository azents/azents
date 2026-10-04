"""Deterministic supervision proves model latency never owns the database lease."""

import asyncio
import dataclasses
import datetime
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, Mock

import pytest

from azents.core.historical_memory_consolidation import ConsolidationDisposition
from azents.core.historical_memory_publication import (
    ConsolidationCoverage,
    ConsolidationWorkDisposition,
    validate_consolidation_overview,
)
from azents.core.historical_memory_system_setting import HistoricalMemoryExecutionConfig
from azents.job_runtime.types import JobExecutionContext, JobRequest
from azents.rdb.models.historical_memory_consolidation import RDBConsolidationUnit
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
    DraftFileChange,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationClaim,
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.publication import (
    ConsolidationPublicationOutcome,
    ConsolidationPublicationRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
)
from azents.services.historical_memory.consolidation_discovery import (
    HistoricalMemoryConsolidationDiscoveryService,
)
from azents.services.historical_memory.consolidation_job import (
    HistoricalMemoryConsolidationService,
    execute_historical_memory_consolidation_job,
    supervise_consolidation_attempt,
)
from azents.services.historical_memory.constants import (
    HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY,
)
from azents.testing.consolidation import (
    consolidation_deadline,
    seed_consolidation_corpus,
)


class _Clock:
    def __init__(self) -> None:
        self.requests: asyncio.Queue[float] = asyncio.Queue()
        self.ticks: asyncio.Queue[None] = asyncio.Queue()

    def time(self) -> float:
        return asyncio.get_running_loop().time()

    async def sleep(self, delay: float) -> None:
        await self.requests.put(delay)
        await self.ticks.get()


@dataclasses.dataclass
class _PausedHost:
    claim: ConsolidationClaim
    ownership_repository: ConsolidationOwnershipRepository
    publication_repository: ConsolidationPublicationRepository
    started: asyncio.Event = dataclasses.field(
        init=False, default_factory=asyncio.Event
    )
    release: asyncio.Event = dataclasses.field(
        init=False, default_factory=asyncio.Event
    )
    stopped: asyncio.Event = dataclasses.field(
        init=False, default_factory=asyncio.Event
    )
    closed: bool = dataclasses.field(init=False, default=False)

    async def run(self) -> ConsolidationPublicationOutcome:
        self.started.set()
        try:
            await self.release.wait()
            return ConsolidationPublicationOutcome("a" * 32)
        finally:
            self.stopped.set()

    async def close(self) -> None:
        self.closed = True


async def _host(manager: SessionManager[WriteSession]) -> _PausedHost:
    corpus = await seed_consolidation_corpus(manager)
    ownership = ConsolidationOwnershipRepository(manager)
    claim = await ownership.claim(corpus.team, deadline=consolidation_deadline())
    assert claim is not None
    return _PausedHost(claim, ownership, ConsolidationPublicationRepository(manager))


async def test_heartbeat_renews_while_model_is_blocked_without_foreground_lock(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    host = await _host(rdb_session_manager)
    clock = _Clock()
    execution = asyncio.create_task(supervise_consolidation_attempt(host, clock=clock))
    await host.started.wait()
    assert await clock.requests.get() == 30
    before = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=60)
    async with rdb_session_manager() as session:
        unit = await session.read_session.get(RDBConsolidationUnit, host.claim.unit_id)
        assert unit is not None
        unit.lease_until = before
    await clock.ticks.put(None)
    assert await clock.requests.get() == 30
    async with rdb_session_manager() as session:
        unit = await session.read_session.get(RDBConsolidationUnit, host.claim.unit_id)
        assert (
            unit is not None
            and unit.lease_until is not None
            and unit.lease_until > before
        )
    assert not execution.done()
    host.release.set()
    assert (await execution).revision_id == "a" * 32
    assert host.closed and host.stopped.is_set()


async def test_unconfirmed_ownership_cancels_and_quiesces_the_blocked_host(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    host = await _host(rdb_session_manager)
    clock = _Clock()
    execution = asyncio.create_task(supervise_consolidation_attempt(host, clock=clock))
    await host.started.wait()
    assert await clock.requests.get() == 30
    async with rdb_session_manager() as session:
        unit = await session.read_session.get(RDBConsolidationUnit, host.claim.unit_id)
        assert unit is not None
        unit.owner_token = "b" * 32
    await clock.ticks.put(None)
    with pytest.raises(ConsolidationAuthorityError):
        await execution
    assert host.closed and host.stopped.is_set()
    assert (
        await host.publication_repository.inspect_outcome(host.claim.principal) is None
    )


async def test_shutdown_preserves_cancellation_and_drops_host_lifecycle(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    host = await _host(rdb_session_manager)
    clock = _Clock()
    execution = asyncio.create_task(supervise_consolidation_attempt(host, clock=clock))
    await host.started.wait()
    assert await clock.requests.get() == 30
    execution.cancel("worker-shutdown")
    with pytest.raises(asyncio.CancelledError, match="worker-shutdown"):
        await execution
    assert host.closed and host.stopped.is_set()


async def test_already_elapsed_attempt_closes_even_a_never_started_host(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    host = await _host(rdb_session_manager)
    host.claim = dataclasses.replace(
        host.claim,
        deadline_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1),
    )
    with pytest.raises(TimeoutError):
        await supervise_consolidation_attempt(host, clock=_Clock())
    assert host.closed


class _Container:
    def __init__(self, service: object, discovery: object) -> None:
        self.service = service
        self.discovery = discovery

    async def solve(self, target: type[object]) -> object:
        if target is HistoricalMemoryConsolidationService:
            return self.service
        assert target is HistoricalMemoryConsolidationDiscoveryService
        return self.discovery


class _CloseDeniedPause(_PausedHost):
    async def close(self) -> None:
        raise PermissionError("Synthetic late cleanup authority loss")


async def test_late_cleanup_error_does_not_replace_original_shutdown_cancellation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    base = await _host(rdb_session_manager)
    attempt = _CloseDeniedPause(
        base.claim, base.ownership_repository, base.publication_repository
    )
    clock = _Clock()
    execution = asyncio.create_task(
        supervise_consolidation_attempt(attempt, clock=clock)
    )
    await attempt.started.wait()
    assert await clock.requests.get() == 30
    execution.cancel("worker-shutdown")
    with pytest.raises(asyncio.CancelledError, match="worker-shutdown") as error:
        await execution
    assert isinstance(error.value.__cause__, PermissionError)
    assert attempt.stopped.is_set()


@dataclasses.dataclass
class _CommittedPause(_PausedHost):
    publisher: Callable[[], Awaitable[ConsolidationPublicationOutcome]]

    async def run(self) -> ConsolidationPublicationOutcome:
        committed = await self.publisher()
        self.started.set()
        try:
            await self.release.wait()
            return committed
        finally:
            self.stopped.set()


async def test_publication_commit_wins_heartbeat_loss_during_final_quiescence(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    base = await _host(rdb_session_manager)
    principal = base.claim.principal
    work = ConsolidationWorkRepository(rdb_session_manager)
    page = await work.page(principal, after_sequence=None, limit=50)
    coverage = ConsolidationCoverage(
        dispositions=(
            ConsolidationWorkDisposition(
                work_id=page.entries[0].work_id,
                action=ConsolidationDisposition.OMITTED,
                reason="No useful continuation",
            ),
        )
    )
    drafts = ConsolidationDraftRepository(rdb_session_manager)
    observed = await drafts.observe(principal, path="summary.md")
    await drafts.mutate(
        principal,
        tool_call_id="ready-empty",
        request_digest="a" * 64,
        expected_draft_revision_id=observed.draft_revision_id,
        expected_observation_epoch=observed.observation_epoch,
        changes=[
            DraftFileChange(
                "summary.md", None, "## Historical Context\n\n## Source Routes\n"
            ),
            DraftFileChange("coverage.json", None, coverage.model_dump_json()),
        ],
    )
    frozen = await base.publication_repository.freeze(principal)
    await work.record_coverage(
        principal, expected_draft_revision_id=frozen.revision_id, coverage=coverage
    )

    async def publish() -> ConsolidationPublicationOutcome:
        return await base.publication_repository.publish(
            principal,
            expected_draft_revision_id=frozen.revision_id,
            expected_observation_epoch=frozen.observation_epoch,
            overview=validate_consolidation_overview(
                key=principal.unit, markdown=frozen.markdown
            ),
        )

    attempt = _CommittedPause(
        base.claim, base.ownership_repository, base.publication_repository, publish
    )
    clock = _Clock()
    execution = asyncio.create_task(
        supervise_consolidation_attempt(attempt, clock=clock)
    )
    async with asyncio.timeout(5):
        await attempt.started.wait()
        assert await clock.requests.get() == 30
        await clock.ticks.put(None)
        outcome = await execution
    assert attempt.closed and attempt.stopped.is_set()
    assert await base.publication_repository.inspect_outcome(principal) == outcome


async def test_handler_requests_productive_pending_continuation_after_publication(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    service = Mock()
    service.run_unit = AsyncMock(return_value=ConsolidationPublicationOutcome("a" * 32))
    discovery = Mock()
    discovery.dispatch_pending = AsyncMock(return_value=1)
    context = JobExecutionContext(
        request=JobRequest(
            handler_key=HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY,
            execution_key="synthetic-unit",
            deadline=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(minutes=10),
            payload={
                "unit": corpus.team.model_dump(mode="json"),
                "execution_policy": {
                    "max_turns": 7,
                    "timeout_seconds": 900,
                },
            },
        ),
        container=_Container(service, discovery),  # ty: ignore[invalid-argument-type] # Focused container implements only solve().
    )
    result = await execute_historical_memory_consolidation_job(context)
    assert result == {"published_revision_id": "a" * 32, "coalesced": False}
    service.run_unit.assert_awaited_once_with(
        corpus.team,
        execution_policy=HistoricalMemoryExecutionConfig(
            max_turns=7, timeout_seconds=900
        ),
        deadline=context.request.deadline,
    )
    discovery.dispatch_pending.assert_awaited_once_with(agent_id=corpus.team.agent_id)
