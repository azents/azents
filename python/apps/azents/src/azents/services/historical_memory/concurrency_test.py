"""Historical Memory reserved Job Runtime capacity integration tests."""

import asyncio
import dataclasses
import datetime

from azcommon import di

from azents.job_runtime.local import LocalJobRuntime
from azents.job_runtime.registry import get_job_handler_registry
from azents.job_runtime.types import (
    JobExecutionContext,
    JobHandlerRegistry,
    JobOutcomeStatus,
    JobPayload,
    JobRequest,
)
from azents.scheduler.executor import SCHEDULER_JOB_HANDLER_KEY
from azents.services.historical_memory.job import (
    HISTORICAL_MEMORY_MAX_CONCURRENCY,
    HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
)


async def test_historical_backlog_preserves_non_memory_runtime_capacity() -> None:
    """A queued Historical backlog cannot take the slot reserved for ordinary work."""
    historical_started = 0
    all_memory_slots_started = asyncio.Event()
    release_memory = asyncio.Event()
    ordinary_started = asyncio.Event()

    async def historical_handler(_context: JobExecutionContext) -> JobPayload:
        nonlocal historical_started
        historical_started += 1
        if historical_started == HISTORICAL_MEMORY_MAX_CONCURRENCY:
            all_memory_slots_started.set()
        await release_memory.wait()
        return {"prepared": True}

    async def ordinary_handler(_context: JobExecutionContext) -> JobPayload:
        ordinary_started.set()
        return {"ordinary": True}

    definitions = get_job_handler_registry().definitions()
    memory_definition = next(
        definition
        for definition in definitions
        if definition.key == HISTORICAL_MEMORY_PREPARE_HANDLER_KEY
    )
    ordinary_definition = next(
        definition
        for definition in definitions
        if definition.key == SCHEDULER_JOB_HANDLER_KEY
    )
    assert memory_definition.max_concurrency == HISTORICAL_MEMORY_MAX_CONCURRENCY
    assert 1 <= HISTORICAL_MEMORY_MAX_CONCURRENCY < 16
    runtime = LocalJobRuntime(
        handlers=JobHandlerRegistry(
            (
                dataclasses.replace(memory_definition, handler=historical_handler),
                dataclasses.replace(ordinary_definition, handler=ordinary_handler),
            )
        ),
        container_factory=di.Container,
        max_concurrency=16,
        cancellation_grace_seconds=0.1,
    )
    deadline = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
    try:
        memory_handles = [
            await runtime.submit(
                JobRequest(
                    handler_key=HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
                    execution_key=f"memory-{index}",
                    deadline=deadline,
                    payload={},
                )
            )
            for index in range(HISTORICAL_MEMORY_MAX_CONCURRENCY + 1)
        ]
        async with asyncio.timeout(5):
            await all_memory_slots_started.wait()
            ordinary_handle = await runtime.submit(
                JobRequest(
                    handler_key=SCHEDULER_JOB_HANDLER_KEY,
                    execution_key="ordinary",
                    deadline=deadline,
                    payload={},
                )
            )
            ordinary_outcome = await ordinary_handle.wait()
        assert ordinary_started.is_set()
        assert ordinary_outcome.status is JobOutcomeStatus.SUCCEEDED
        assert historical_started == HISTORICAL_MEMORY_MAX_CONCURRENCY
        assert not release_memory.is_set()
        release_memory.set()
        outcomes = await asyncio.gather(*(handle.wait() for handle in memory_handles))
        assert all(outcome.status is JobOutcomeStatus.SUCCEEDED for outcome in outcomes)
        assert historical_started == HISTORICAL_MEMORY_MAX_CONCURRENCY + 1
    finally:
        release_memory.set()
        await runtime.close()
    assert runtime.active_count == 0
