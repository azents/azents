"""Job Runtime dependency composition tests."""

import asyncio
import datetime
from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from azcommon import di

from azents.core.enums import JobRuntimeBackend
from azents.job_runtime.deps import (
    JobRuntimeBackendUnavailableError,
    get_job_runtime,
)
from azents.job_runtime.local import LocalJobRuntime
from azents.job_runtime.types import (
    JobExecutionContext,
    JobHandlerDefinition,
    JobHandlerRegistry,
    JobOutcomeStatus,
    JobRequest,
)
from azents.utils.appctx import AppContext


@pytest.mark.asyncio
async def test_get_job_runtime_is_one_appcontext_singleton() -> None:
    """Every producer in one process resolves the same Runtime instance."""
    config = MagicMock(job_runtime_backend=JobRuntimeBackend.LOCAL)
    appctx = AppContext(cast(Any, config))
    container = di.Container()

    first = await get_job_runtime(appctx, cast(Any, config), container)
    second = await get_job_runtime(appctx, cast(Any, config), container)

    assert isinstance(first, LocalJobRuntime)
    assert second is first

    await appctx.close()
    await container.drain()


@pytest.mark.asyncio
async def test_get_job_runtime_rejects_reserved_temporal_backend() -> None:
    """Reserved Temporal selection fails instead of falling back to Local."""
    config = MagicMock(job_runtime_backend=JobRuntimeBackend.TEMPORAL)
    appctx = AppContext(cast(Any, config))

    with pytest.raises(
        JobRuntimeBackendUnavailableError,
        match="Temporal Job Runtime backend is not implemented",
    ):
        await get_job_runtime(appctx, cast(Any, config), di.Container())

    await appctx.close()


@pytest.mark.asyncio
async def test_appcontext_waits_for_quarantined_handler_before_resources_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-close retains shared resources until an overrun handler settles."""
    config = MagicMock(job_runtime_backend=JobRuntimeBackend.LOCAL)
    appctx = AppContext(cast(Any, config))
    container = di.Container()
    resource_closed = asyncio.Event()
    handler_cancelled = asyncio.Event()
    release_handler = asyncio.Event()

    async def resource() -> AsyncIterator[object]:
        try:
            yield object()
        finally:
            resource_closed.set()

    async def handler(_context: JobExecutionContext) -> None:
        await appctx.get_variable("handler-resource", resource)
        while not release_handler.is_set():
            try:
                await release_handler.wait()
            except asyncio.CancelledError:
                handler_cancelled.set()

    registry = JobHandlerRegistry(
        (JobHandlerDefinition(key="test.quarantine", handler=handler),)
    )
    monkeypatch.setattr(
        "azents.job_runtime.deps.get_job_handler_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        "azents.job_runtime.deps._LOCAL_CANCELLATION_GRACE_SECONDS",
        0.01,
    )
    runtime = await get_job_runtime(appctx, cast(Any, config), container)
    handle = await runtime.submit(
        JobRequest(
            handler_key="test.quarantine",
            execution_key="quarantine",
            deadline=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(seconds=0.01),
            payload={},
        )
    )
    close_task: asyncio.Task[None] | None = None
    try:
        outcome = await asyncio.wait_for(handle.wait(), timeout=0.2)
        assert outcome.status is JobOutcomeStatus.TIMED_OUT
        assert handler_cancelled.is_set()

        close_task = asyncio.create_task(appctx.close())
        await asyncio.sleep(0)
        assert not close_task.done()
        assert not resource_closed.is_set()
        close_task.cancel()
        await asyncio.sleep(0)
        assert not close_task.done()
        assert not resource_closed.is_set()
    finally:
        release_handler.set()
        if close_task is None:
            close_task = asyncio.create_task(appctx.close())
        if close_task.cancelled():
            pass
        elif close_task.cancelling():
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(close_task, timeout=0.2)
        else:
            await asyncio.wait_for(close_task, timeout=0.2)
        await container.drain()

    assert resource_closed.is_set()
