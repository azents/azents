"""Sampling preserves Stage 1 semantics and reports routing, not publication."""

import datetime
from unittest.mock import AsyncMock

import pytest

from azents.services.historical_memory.consolidation_discovery import (
    HistoricalMemoryConsolidationDiscoveryService,
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


def _service() -> HistoricalMemorySamplingService:
    discovery = AsyncMock(spec=HistoricalMemoryDiscoveryService)
    discovery.admit_and_list_due_agents.return_value = HistoricalMemoryAdmissionSample(
        1, ("a" * 32,)
    )
    preparation = AsyncMock(spec=HistoricalMemoryPreparationService)
    preparation.prepare_agent.return_value = HistoricalMemoryPreparationSummary(
        1, 1, 0, 0, 0
    )
    dispatch = AsyncMock(spec=HistoricalMemoryConsolidationDiscoveryService)
    dispatch.dispatch_pending.return_value = 2
    return HistoricalMemorySamplingService(discovery, preparation, dispatch)


async def test_stage1_sampling_uses_aware_time_and_real_attempt_deadline() -> None:
    service = _service()
    now = datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)
    before = datetime.datetime.now(datetime.UTC)
    report = await service.sample_agent(agent_id="a" * 32, now=now, consolidate=False)
    assert report.prepared == 1 and report.consolidation_dispatched == 0
    assert isinstance(service.discovery, AsyncMock)
    assert isinstance(service.preparation, AsyncMock)
    assert isinstance(service.consolidation_discovery, AsyncMock)
    service.discovery.admit_and_list_due_agents.assert_awaited_once_with(
        now=now, agent_id="a" * 32
    )
    deadline = service.preparation.prepare_agent.await_args.kwargs["deadline"]
    assert before < deadline < before + datetime.timedelta(seconds=120)
    service.consolidation_discovery.dispatch_pending.assert_not_awaited()


async def test_not_due_preparation_routes_work_without_claiming_publish() -> None:
    service = _service()
    assert isinstance(service.discovery, AsyncMock)
    assert isinstance(service.preparation, AsyncMock)
    assert isinstance(service.consolidation_discovery, AsyncMock)
    service.discovery.admit_and_list_due_agents.return_value = (
        HistoricalMemoryAdmissionSample(0, ())
    )
    report = await service.sample_agent(
        agent_id="a" * 32, now=datetime.datetime.now(datetime.UTC), consolidate=True
    )
    assert report.prepared == 0 and report.consolidation_dispatched == 2
    assert "consolidation_published" not in report.__dataclass_fields__
    service.preparation.prepare_agent.assert_not_awaited()
    service.consolidation_discovery.dispatch_pending.assert_awaited_once_with(
        agent_id="a" * 32
    )


async def test_dispatch_error_propagates_instead_of_inventing_publication_health() -> (
    None
):
    service = _service()
    assert isinstance(service.consolidation_discovery, AsyncMock)
    service.consolidation_discovery.dispatch_pending.side_effect = RuntimeError(
        "routing failed"
    )
    with pytest.raises(RuntimeError, match="routing failed"):
        await service.sample_agent(
            agent_id="a" * 32, now=datetime.datetime.now(datetime.UTC), consolidate=True
        )


async def test_sampling_rejects_naive_operator_time_before_preparation() -> None:
    service = _service()
    with pytest.raises(ValueError, match="aware timestamp"):
        await service.sample_agent(
            agent_id="a" * 32, now=datetime.datetime(2099, 1, 1), consolidate=True
        )
    assert isinstance(service.discovery, AsyncMock)
    service.discovery.admit_and_list_due_agents.assert_not_awaited()
