"""Registered Historical Memory preparation Job Runtime handler."""

import dataclasses
import os

from pydantic import BaseModel, Field

from azents.job_runtime.types import (
    JobExecutionContext,
    JobPayload,
    validate_job_payload,
)
from azents.services.historical_memory.constants import (
    HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
)
from azents.services.historical_memory.preparation import (
    HistoricalMemoryPreparationService,
)

_DEFAULT_MAX_CONCURRENCY = 12
_MAX_PREPARATION_CONCURRENCY = 12


class HistoricalMemoryPreparationJobPayload(BaseModel):
    """Validated target-Agent preparation request."""

    agent_id: str = Field(min_length=32, max_length=32)


def _max_concurrency() -> int:
    raw = os.environ.get(
        "AZ_HISTORICAL_MEMORY_MAX_CONCURRENCY",
        str(_DEFAULT_MAX_CONCURRENCY),
    )
    value = int(raw)
    if value < 1 or value > _MAX_PREPARATION_CONCURRENCY:
        raise ValueError(
            "AZ_HISTORICAL_MEMORY_MAX_CONCURRENCY must be between 1 and 12."
        )
    return value


HISTORICAL_MEMORY_MAX_CONCURRENCY = _max_concurrency()


async def execute_historical_memory_preparation_job(
    context: JobExecutionContext,
) -> JobPayload | None:
    """Run one bounded target-Agent source batch under reserved concurrency."""
    from azents.services.historical_memory.consolidation_discovery import (  # noqa: PLC0415
        HistoricalMemoryConsolidationDiscoveryService,
    )

    payload = HistoricalMemoryPreparationJobPayload.model_validate(
        context.request.payload
    )
    service = await context.container.solve(HistoricalMemoryPreparationService)
    summary = await service.prepare_agent(
        agent_id=payload.agent_id,
        deadline=context.request.deadline,
        now=None,
    )
    if summary.prepared or summary.empty:
        consolidation = await context.container.solve(
            HistoricalMemoryConsolidationDiscoveryService
        )
        await consolidation.dispatch_pending(agent_id=payload.agent_id)
    return validate_job_payload(dataclasses.asdict(summary))


__all__ = [
    "HISTORICAL_MEMORY_PREPARE_HANDLER_KEY",
    "HISTORICAL_MEMORY_MAX_CONCURRENCY",
    "execute_historical_memory_preparation_job",
]
