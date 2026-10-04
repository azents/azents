"""Ordinary service sampling uses real deadlines/ownership and truthful outcomes."""

import datetime
from unittest.mock import AsyncMock

import pytest

from azents.core.historical_memory_publication import ConsolidationOutputError
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.publication import (
    ConsolidationPublicationOutcome,
)
from azents.services.historical_memory.consolidation_job import (
    HistoricalMemoryConsolidationService,
)
from azents.services.historical_memory.discovery import (
    HistoricalMemoryAdmissionSample,
    HistoricalMemoryDiscoveryService,
)
from azents.services.historical_memory.preparation import (
    HistoricalMemoryPreparationService,
    HistoricalMemoryPreparationSummary,
)
from azents.services.historical_memory.sampling import HistoricalMemorySamplingService
from azents.testing.consolidation import seed_consolidation_corpus


async def test_stage1_sampler_shares_aware_time_but_preserves_real_attempt_deadline(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    discovery = AsyncMock(spec=HistoricalMemoryDiscoveryService)
    discovery.admit_and_list_due_agents.return_value = HistoricalMemoryAdmissionSample(
        1, ("a" * 32,)
    )
    preparation = AsyncMock(spec=HistoricalMemoryPreparationService)
    preparation.prepare_agent.return_value = HistoricalMemoryPreparationSummary(
        1, 1, 0, 0, 0
    )
    consolidation = AsyncMock(spec=HistoricalMemoryConsolidationService)
    service = HistoricalMemorySamplingService(
        rdb_session_manager, discovery, preparation, consolidation
    )
    now = datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)
    real_before = datetime.datetime.now(datetime.UTC)
    report = await service.sample_agent(agent_id="a" * 32, now=now, consolidate=False)
    assert report.prepared == 1 and report.consolidation_due == 0
    discovery.admit_and_list_due_agents.assert_awaited_once_with(
        now=now, agent_id="a" * 32
    )
    kwargs = preparation.prepare_agent.await_args.kwargs
    assert kwargs["now"] == now
    assert (
        real_before < kwargs["deadline"] < real_before + datetime.timedelta(seconds=120)
    )
    consolidation.run_unit.assert_not_awaited()


async def test_not_due_stage1_does_not_skip_pending_consolidation_or_invent_success(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    discovery = AsyncMock(spec=HistoricalMemoryDiscoveryService)
    discovery.admit_and_list_due_agents.return_value = HistoricalMemoryAdmissionSample(
        0, ()
    )
    preparation = AsyncMock(spec=HistoricalMemoryPreparationService)
    consolidation = AsyncMock(spec=HistoricalMemoryConsolidationService)
    consolidation.run_unit.side_effect = [
        ConsolidationPublicationOutcome("a" * 32),
        None,
    ]
    service = HistoricalMemorySamplingService(
        rdb_session_manager, discovery, preparation, consolidation
    )
    report = await service.sample_agent(
        agent_id=corpus.team.agent_id,
        now=datetime.datetime.now(datetime.UTC),
        consolidate=True,
    )
    assert report.prepared == 0 and report.consolidation_due == 2
    assert report.consolidation_published == 1 and report.consolidation_unclaimed == 1
    assert report.consolidation_failed == 0
    preparation.prepare_agent.assert_not_awaited()
    assert {call.args[0] for call in consolidation.run_unit.await_args_list} == {
        corpus.team,
        corpus.personal,
    }


async def test_known_validation_failure_is_counted_but_unexpected_errors_propagate(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    discovery = AsyncMock(spec=HistoricalMemoryDiscoveryService)
    discovery.admit_and_list_due_agents.return_value = HistoricalMemoryAdmissionSample(
        0, ()
    )
    preparation = AsyncMock(spec=HistoricalMemoryPreparationService)
    consolidation = AsyncMock(spec=HistoricalMemoryConsolidationService)
    consolidation.run_unit.side_effect = [
        ConsolidationOutputError("Expected authored validation failure"),
        None,
    ]
    service = HistoricalMemorySamplingService(
        rdb_session_manager, discovery, preparation, consolidation
    )
    report = await service.sample_agent(
        agent_id=corpus.team.agent_id,
        now=datetime.datetime.now(datetime.UTC),
        consolidate=True,
    )
    assert report.consolidation_failed == 1 and report.consolidation_published == 0
    consolidation.run_unit.side_effect = RuntimeError("Unexpected model failure")
    with pytest.raises(RuntimeError, match="Unexpected model failure"):
        await service.sample_agent(
            agent_id=corpus.team.agent_id,
            now=datetime.datetime.now(datetime.UTC),
            consolidate=True,
        )
