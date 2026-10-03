"""Historical Memory reserved Job Runtime capacity integration tests."""

import asyncio
import dataclasses
import datetime

import pytest
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
from azents.services.historical_memory.constants import (
    HISTORICAL_MEMORY_COMBINED_MAX_CONCURRENCY,
    HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY,
    HISTORICAL_MEMORY_CONSOLIDATION_MAX_CONCURRENCY,
)
from azents.services.historical_memory.job import (
    HISTORICAL_MEMORY_MAX_CONCURRENCY,
    HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
    _max_concurrency,
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


async def test_preparation_and_consolidation_leave_two_ordinary_local_slots() -> None:
    counts = {"preparation": 0, "consolidation": 0}
    preparation_ready, consolidation_ready = asyncio.Event(), asyncio.Event()
    release = asyncio.Event()

    async def preparation(_context: JobExecutionContext) -> JobPayload:
        counts["preparation"] += 1
        if counts["preparation"] == HISTORICAL_MEMORY_MAX_CONCURRENCY:
            preparation_ready.set()
        await release.wait()
        return {"prepared": True}

    async def consolidation(_context: JobExecutionContext) -> JobPayload:
        counts["consolidation"] += 1
        if counts["consolidation"] == HISTORICAL_MEMORY_CONSOLIDATION_MAX_CONCURRENCY:
            consolidation_ready.set()
        await release.wait()
        return {"consolidated": True}

    async def ordinary(_context: JobExecutionContext) -> JobPayload:
        return {"ordinary": True}

    handlers = {
        HISTORICAL_MEMORY_PREPARE_HANDLER_KEY: preparation,
        HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY: consolidation,
        SCHEDULER_JOB_HANDLER_KEY: ordinary,
    }
    definitions = tuple(
        dataclasses.replace(definition, handler=handlers[definition.key])
        for definition in get_job_handler_registry().definitions()
        if definition.key in handlers
    )
    runtime = LocalJobRuntime(
        handlers=JobHandlerRegistry(definitions),
        container_factory=di.Container,
        max_concurrency=16,
        cancellation_grace_seconds=0.1,
    )
    deadline = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
    try:
        handles = []
        for key, maximum in (
            (HISTORICAL_MEMORY_PREPARE_HANDLER_KEY, HISTORICAL_MEMORY_MAX_CONCURRENCY),
            (
                HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY,
                HISTORICAL_MEMORY_CONSOLIDATION_MAX_CONCURRENCY,
            ),
        ):
            for index in range(maximum + 1):
                handles.append(
                    await runtime.submit(
                        JobRequest(
                            handler_key=key,
                            execution_key=f"{key}:{index}",
                            deadline=deadline,
                            payload={},
                        )
                    )
                )
        async with asyncio.timeout(5):
            await preparation_ready.wait()
            await consolidation_ready.wait()
            assert sum(counts.values()) == HISTORICAL_MEMORY_COMBINED_MAX_CONCURRENCY
            ordinary_handles = [
                await runtime.submit(
                    JobRequest(
                        handler_key=SCHEDULER_JOB_HANDLER_KEY,
                        execution_key=f"ordinary:{index}",
                        deadline=deadline,
                        payload={},
                    )
                )
                for index in range(2)
            ]
            outcomes = await asyncio.gather(
                *(handle.wait() for handle in ordinary_handles)
            )
            assert all(
                outcome.status is JobOutcomeStatus.SUCCEEDED for outcome in outcomes
            )
        assert not release.is_set()
        release.set()
        assert all(
            outcome.status is JobOutcomeStatus.SUCCEEDED
            for outcome in await asyncio.gather(*(handle.wait() for handle in handles))
        )
    finally:
        release.set()
        await runtime.close()
    assert runtime.active_count == 0


@pytest.mark.parametrize("value", ["13", "15", "16", "0"])
def test_configured_preparation_cannot_exceed_combined_memory_capacity(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("AZ_HISTORICAL_MEMORY_MAX_CONCURRENCY", value)
    with pytest.raises(ValueError, match="must not exceed 14"):
        _max_concurrency()


def test_preparation_default_is_twelve_with_two_consolidation_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZ_HISTORICAL_MEMORY_MAX_CONCURRENCY", raising=False)
    assert _max_concurrency() == 12
    assert HISTORICAL_MEMORY_CONSOLIDATION_MAX_CONCURRENCY == 2
