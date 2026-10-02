"""Historical Memory discovery and dispatch tests."""

import datetime
from unittest.mock import AsyncMock

import pytest

from azents.job_runtime.types import JobRequest
from azents.services.historical_memory.discovery import (
    HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
    HistoricalMemoryDiscoveryService,
)


async def test_discovery_uses_fresh_window_and_dispatches_agent_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One pass admits first-window sources and submits without waiting."""
    now = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)

    class _DateTime(datetime.datetime):
        @classmethod
        def now(
            cls,
            tz: datetime.tzinfo | None = None,
        ) -> datetime.datetime:
            assert tz is datetime.UTC
            return now

    monkeypatch.setattr(
        "azents.services.historical_memory.discovery.datetime.datetime",
        _DateTime,
    )
    repository = AsyncMock()
    repository.admit_eligible_sources.return_value = ["s" * 32, "t" * 32]
    repository.list_due_agent_ids.return_value = ["a" * 32, "b" * 32]
    runtime = AsyncMock()
    service = HistoricalMemoryDiscoveryService(
        repository=repository,
        job_runtime=runtime,
    )

    summary = await service.discover_once()

    assert summary.admitted == 2
    assert summary.due_agents == 2
    assert summary.dispatched == 2
    repository.admit_eligible_sources.assert_awaited_once_with(
        agent_id=None,
        now=now,
        oldest_activity_at=now - datetime.timedelta(days=10),
        inactive_before=now - datetime.timedelta(hours=6),
        limit=500,
    )
    repository.list_due_agent_ids.assert_awaited_once_with(
        now=now,
        inactive_before=now - datetime.timedelta(hours=6),
        limit=25,
    )
    requests = [call.args[0] for call in runtime.submit.await_args_list]
    assert all(isinstance(request, JobRequest) for request in requests)
    assert [request.handler_key for request in requests] == [
        HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
        HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
    ]
    assert [request.execution_key for request in requests] == [
        f"historical-memory:{'a' * 32}",
        f"historical-memory:{'b' * 32}",
    ]
    assert all(
        request.deadline == now + datetime.timedelta(minutes=30) for request in requests
    )


async def test_explicit_sample_is_scoped_to_one_agent_without_dispatch() -> None:
    """A testenv sample cannot admit or dispatch another Agent's sources."""
    sampled_at = datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)
    repository = AsyncMock()
    repository.admit_eligible_sources.return_value = ["s" * 32]
    repository.list_due_for_agent.return_value = [object()]
    runtime = AsyncMock()
    service = HistoricalMemoryDiscoveryService(
        repository=repository, job_runtime=runtime
    )
    sample = await service.admit_and_list_due_agents(
        now=sampled_at,
        agent_id="a" * 32,
    )
    assert sample.admitted == 1
    assert sample.due_agent_ids == ("a" * 32,)
    repository.admit_eligible_sources.assert_awaited_once_with(
        agent_id="a" * 32,
        now=sampled_at,
        oldest_activity_at=sampled_at - datetime.timedelta(days=10),
        inactive_before=sampled_at - datetime.timedelta(hours=6),
        limit=500,
    )
    repository.list_due_agent_ids.assert_not_awaited()
    runtime.submit.assert_not_awaited()


async def test_sample_rejects_naive_time_before_repository_io() -> None:
    """A sampling instant cannot silently acquire local timezone authority."""
    repository = AsyncMock()
    service = HistoricalMemoryDiscoveryService(
        repository=repository,
        job_runtime=AsyncMock(),
    )
    with pytest.raises(ValueError, match="aware"):
        await service.admit_and_list_due_agents(
            now=datetime.datetime(2099, 1, 1),
            agent_id="a" * 32,
        )
    repository.admit_eligible_sources.assert_not_awaited()
