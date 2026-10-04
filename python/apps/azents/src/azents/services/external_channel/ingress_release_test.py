"""Release service real-PG closure and actual Local Job Runtime acceptance."""

import asyncio
import datetime

import pytest
from azcommon import di
from fastapi import HTTPException

from azents.api.testenv.external_channel_ingress.v1 import (
    IngressOwnerRequest,
    release_active_ingress,
)
from azents.job_runtime.local import JobRuntimeClosedError, LocalJobRuntime
from azents.job_runtime.types import (
    JobExecutionContext,
    JobHandle,
    JobHandlerDefinition,
    JobHandlerRegistry,
    JobOutcome,
    JobPayload,
    JobRequest,
    JobRuntime,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.external_channel.ingress_control_read_test import (
    _MISSING,
    _Boundary,
    _ReadFault,
    _reads,
    _seed,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.services.external_channel.ingress_release import (
    ExternalChannelIngressReleaseService,
)


class _Handle(JobHandle):
    async def wait(self) -> JobOutcome:
        raise AssertionError("Release must not await a submitted job.")


class _Runtime(JobRuntime):
    """Check real SQL completion before every external submission outcome."""

    def __init__(self, boundary: _Boundary, outcome: str) -> None:
        self.boundary = boundary
        self.outcome = outcome
        self.requests: list[JobRequest] = []

    @property
    def active_count(self) -> int:
        self.boundary.closed()
        return len(self.requests)

    @property
    def shutdown_drain_seconds(self) -> float | None:
        self.boundary.closed()
        return None

    async def submit(self, request: JobRequest) -> JobHandle:
        self.boundary.closed()
        assert self.boundary.events == ["open", "commit", "commit", "closed"]
        self.requests.append(request)
        if self.outcome == "error":
            raise JobRuntimeClosedError("test Runtime is closing")
        if self.outcome == "cancel":
            raise asyncio.CancelledError()
        assert self.outcome == "success"
        return _Handle()


async def test_missing_read_commits_before_unchanged_api_404_without_submit(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    boundary = _Boundary(rdb_session_manager)
    runtime = _Runtime(boundary, "success")
    service = ExternalChannelIngressReleaseService(
        repository=_reads(boundary, ExternalChannelIngressQueueRepository()),
        runtime=runtime,
    )
    with pytest.raises(HTTPException) as raised:
        await release_active_ingress(IngressOwnerRequest(owner_id=_MISSING), service)
    boundary.closed()
    assert boundary.events == ["open", "commit", "commit", "closed"]
    assert raised.value.status_code == 404
    assert raised.value.detail == "Active ingress owner not found."
    assert runtime.requests == []


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_api_submit_acceptance_error_cancel_follow_actual_read_completion(
    rdb_session_manager: SessionManager[WriteSession], outcome: str
) -> None:
    seed = await _seed(rdb_session_manager)
    boundary = _Boundary(rdb_session_manager)
    runtime = _Runtime(boundary, outcome)
    service = ExternalChannelIngressReleaseService(
        repository=_reads(boundary, ExternalChannelIngressQueueRepository()),
        runtime=runtime,
    )
    earliest = datetime.datetime.now(datetime.UTC)
    if outcome == "success":
        result = await release_active_ingress(
            IngressOwnerRequest(owner_id=seed.owner_id), service
        )
        assert result.accepted
    else:
        with pytest.raises(
            asyncio.CancelledError if outcome == "cancel" else JobRuntimeClosedError
        ):
            await release_active_ingress(
                IngressOwnerRequest(owner_id=seed.owner_id), service
            )
    latest = datetime.datetime.now(datetime.UTC)
    boundary.closed()
    assert len(runtime.requests) == 1
    request = runtime.requests[0]
    assert request.handler_key == "external_channel.ingress"
    assert request.payload == {"owner_id": seed.owner_id}
    assert request.execution_key == (
        f"external-channel-ingress:{seed.owner_id}:2026-08-10T00:00:00.000000+00:00"
    )
    assert earliest + datetime.timedelta(minutes=10) <= request.deadline
    assert request.deadline <= latest + datetime.timedelta(minutes=10)


@pytest.mark.parametrize("cancel", [False, True], ids=["error", "cancel"])
async def test_owner_query_failure_never_returns_missing_or_submits(
    rdb_session_manager: SessionManager[WriteSession], cancel: bool
) -> None:
    seed = await _seed(rdb_session_manager)
    boundary = _Boundary(rdb_session_manager)
    runtime = _Runtime(boundary, "success")
    service = ExternalChannelIngressReleaseService(
        repository=_reads(boundary, _ReadFault(cancel)), runtime=runtime
    )
    with pytest.raises(asyncio.CancelledError if cancel else ValueError):
        await release_active_ingress(
            IngressOwnerRequest(owner_id=seed.owner_id), service
        )
    boundary.closed()
    assert runtime.requests == []
    assert boundary.events == ["open", "closed"]


class _LocalRuntime(LocalJobRuntime):
    """Witness the real Runtime, rather than replace its acceptance semantics."""

    def __init__(self, boundary: _Boundary, handler: JobHandlerDefinition) -> None:
        super().__init__(
            handlers=JobHandlerRegistry((handler,)),
            container_factory=di.Container,
            max_concurrency=1,
            cancellation_grace_seconds=1,
        )
        self.boundary = boundary
        self.requests: list[JobRequest] = []

    async def submit(self, request: JobRequest) -> JobHandle:
        self.boundary.closed()
        self.requests.append(request)
        return await super().submit(request)


async def test_real_local_runtime_accepts_without_waiting_for_handler(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    seed = await _seed(rdb_session_manager)
    boundary = _Boundary(rdb_session_manager)
    entered = asyncio.Event()
    finish = asyncio.Event()
    finished = asyncio.Event()

    async def handler(context: JobExecutionContext) -> JobPayload:
        boundary.closed()
        assert context.request.payload == {"owner_id": seed.owner_id}
        entered.set()
        await finish.wait()
        boundary.closed()
        finished.set()
        return {}

    runtime = _LocalRuntime(
        boundary,
        JobHandlerDefinition(key="external_channel.ingress", handler=handler),
    )
    service = ExternalChannelIngressReleaseService(
        repository=_reads(boundary, ExternalChannelIngressQueueRepository()),
        runtime=runtime,
    )
    try:
        assert await asyncio.wait_for(
            service.release(owner_id=seed.owner_id), timeout=3
        )
        await asyncio.wait_for(entered.wait(), timeout=3)
        boundary.closed()
        assert runtime.active_count == 1
        assert not finished.is_set()
        assert len(runtime.requests) == 1
    finally:
        finish.set()
        await runtime.close()
    assert finished.is_set()


async def test_closed_actual_runtime_propagates_after_completed_read(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    seed = await _seed(rdb_session_manager)
    boundary = _Boundary(rdb_session_manager)

    async def handler(context: JobExecutionContext) -> JobPayload:
        raise AssertionError("A closed Runtime must not invoke a handler.")

    runtime = _LocalRuntime(
        boundary,
        JobHandlerDefinition(key="external_channel.ingress", handler=handler),
    )
    await runtime.close()
    service = ExternalChannelIngressReleaseService(
        repository=_reads(boundary, ExternalChannelIngressQueueRepository()),
        runtime=runtime,
    )
    with pytest.raises(JobRuntimeClosedError):
        await service.release(owner_id=seed.owner_id)
    boundary.closed()
    assert boundary.events == ["open", "commit", "commit", "closed"]
