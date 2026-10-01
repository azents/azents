"""Historical Memory registered Job Runtime handler tests."""

import datetime
from unittest.mock import AsyncMock, Mock

from azents.job_runtime.types import JobExecutionContext, JobRequest
from azents.services.historical_memory.constants import (
    HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
)
from azents.services.historical_memory.job import (
    execute_historical_memory_preparation_job,
)
from azents.services.historical_memory.preparation import (
    HistoricalMemoryPreparationService,
    HistoricalMemoryPreparationSummary,
)


class _Container:
    """Focused task-local container double."""

    def __init__(self, service: object) -> None:
        self.service = service

    async def solve(self, target: type[object]) -> object:
        """Return the configured preparation service."""
        assert target is HistoricalMemoryPreparationService
        return self.service


async def test_registered_handler_runs_bounded_agent_job() -> None:
    """The handler validates identity and returns JSON-safe counters."""
    service = Mock()
    service.prepare_agent = AsyncMock(
        return_value=HistoricalMemoryPreparationSummary(
            attempted=3,
            prepared=2,
            empty=1,
            failed=1,
            quota_advanced=1,
        )
    )
    deadline = datetime.datetime(2026, 10, 1, 12, 30, tzinfo=datetime.UTC)
    context = JobExecutionContext(
        request=JobRequest(
            handler_key=HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
            execution_key=f"historical-memory:{'a' * 32}",
            deadline=deadline,
            payload={"agent_id": "a" * 32},
        ),
        container=_Container(service),  # ty: ignore[invalid-argument-type] # Focused container implements solve().
    )

    result = await execute_historical_memory_preparation_job(context)

    assert result == {
        "attempted": 3,
        "prepared": 2,
        "empty": 1,
        "failed": 1,
        "quota_advanced": 1,
    }
    service.prepare_agent.assert_awaited_once_with(
        agent_id="a" * 32,
        deadline=deadline,
    )
