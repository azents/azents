"""Runner run loop 계약 테스트."""

import asyncio
import dataclasses
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

import pytest

from azents_runtime_control.runner import (
    RunnerControlClient,
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RunnerRegistration,
    RunnerRegistrationAccepted,
    RunnerRunLoop,
    RunnerStateReport,
    RuntimeRunnerOperations,
)


class FakeRunnerControlClient(RunnerControlClient):
    """Runner loop 테스트용 in-memory Control client."""

    def __init__(self) -> None:
        self.operations: list[RunnerOperationEnvelope] = []
        self.claimed_request_ids: list[str] = []
        self.heartbeats: list[tuple[str, int]] = []
        self.reports: list[RunnerStateReport] = []
        self.events: list[RunnerOperationEvent] = []

    async def register_runner(
        self,
        registration: RunnerRegistration,
        *,
        connection_id: str,
        registered_at: datetime,
    ) -> RunnerRegistrationAccepted:
        """Fake Runner registration 을 처리합니다."""
        del registered_at
        return RunnerRegistrationAccepted(
            runtime_id=registration.runtime_id,
            runner_id=registration.runner_id,
            connection_id=connection_id,
            generation=7,
            heartbeat_interval_seconds=20,
        )

    async def heartbeat_runner(
        self,
        *,
        runtime_id: str,
        generation: int,
        heartbeat_at: datetime,
    ) -> bool:
        """Heartbeat 호출을 기록합니다."""
        del heartbeat_at
        self.heartbeats.append((runtime_id, generation))
        return True

    async def report_runner_state(self, report: RunnerStateReport) -> None:
        """Runner state report 를 기록합니다."""
        self.reports.append(report)

    async def claim_next_runner_operation(
        self,
        *,
        runtime_id: str,
        generation: int,
        consumer_id: str,
        block_ms: int,
    ) -> RunnerOperationEnvelope | None:
        """다음 operation 을 하나 반환합니다."""
        del runtime_id, generation, consumer_id, block_ms
        if not self.operations:
            return None
        operation = self.operations.pop(0)
        self.claimed_request_ids.append(operation.request_id)
        return operation

    async def append_runner_event(self, event: RunnerOperationEvent) -> None:
        """Runner event 를 기록합니다."""
        self.events.append(event)


@dataclasses.dataclass
class BlockingOperations(RuntimeRunnerOperations):
    """해제 signal 전까지 operation 을 붙잡는 fake handler 입니다."""

    started: list[str] = dataclasses.field(default_factory=list)
    finished: list[str] = dataclasses.field(default_factory=list)
    _release_events: dict[str, asyncio.Event] = dataclasses.field(default_factory=dict)

    async def handle(self, operation: RunnerOperationEnvelope) -> None:
        """Operation 시작을 기록하고 release 될 때까지 대기합니다."""
        self.started.append(operation.request_id)
        event = self._release_events.setdefault(operation.request_id, asyncio.Event())
        await event.wait()
        self.finished.append(operation.request_id)

    def release(self, request_id: str) -> None:
        """지정한 operation 을 완료시킵니다."""
        self._release_events.setdefault(request_id, asyncio.Event()).set()


@pytest.mark.asyncio
async def test_run_once_schedules_operations_concurrently() -> None:
    """Long-running operation 이 다음 operation scheduling 을 막지 않습니다."""
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    client.operations.extend((_operation("req-1"), _operation("req-2")))
    loop = _loop(client, operations, max_concurrent_operations=2)
    await loop.start()

    assert await loop.run_once(block_ms=0)
    await _wait_for(lambda: operations.started == ["req-1"])
    assert await loop.run_once(block_ms=0)
    await _wait_for(lambda: operations.started == ["req-1", "req-2"])

    operations.release("req-1")
    operations.release("req-2")
    await _wait_for(lambda: operations.finished == ["req-1", "req-2"])
    await loop.run_once(block_ms=0)

    assert client.claimed_request_ids == ["req-1", "req-2"]


@pytest.mark.asyncio
async def test_run_once_respects_max_concurrent_operations() -> None:
    """Concurrency 상한에 닿으면 다음 operation claim 을 미룹니다."""
    client = FakeRunnerControlClient()
    operations = BlockingOperations()
    client.operations.extend((_operation("req-1"), _operation("req-2")))
    loop = _loop(client, operations, max_concurrent_operations=1)
    await loop.start()

    assert await loop.run_once(block_ms=0)
    await _wait_for(lambda: operations.started == ["req-1"])
    assert not await loop.run_once(block_ms=1)
    assert client.claimed_request_ids == ["req-1"]

    operations.release("req-1")
    await _wait_for(lambda: operations.finished == ["req-1"])
    assert await loop.run_once(block_ms=0)
    await _wait_for(lambda: operations.started == ["req-1", "req-2"])
    operations.release("req-2")
    await _wait_for(lambda: operations.finished == ["req-1", "req-2"])
    await loop.run_once(block_ms=0)


def _loop(
    client: FakeRunnerControlClient,
    operations: RuntimeRunnerOperations,
    *,
    max_concurrent_operations: int,
) -> RunnerRunLoop:
    return RunnerRunLoop(
        client=client,
        operations=operations,
        registration=_registration(),
        connection_id="connection-1",
        consumer_id="consumer-1",
        clock=lambda: datetime(2026, 5, 25, tzinfo=UTC),
        monotonic=lambda: 100.0,
        max_concurrent_operations=max_concurrent_operations,
    )


def _registration() -> RunnerRegistration:
    metadata: Mapping[str, str] = {"workspace_path_source": "provider"}
    capabilities: Sequence[str] = ("bash", "file.read")
    return RunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version="agent-runtime-runner.v1",
        capabilities=capabilities,
        health="ok",
        workspace_path="/workspace/agent",
        metadata=metadata,
        auth_credential_id="credential-1",
    )


def _operation(request_id: str) -> RunnerOperationEnvelope:
    payload: Mapping[str, str] = {"command": "sleep 60"}
    return RunnerOperationEnvelope(
        request_id=request_id,
        runtime_id="runtime-1",
        runner_generation=7,
        operation_type="bash",
        payload=payload,
        reply_stream_id="runner:runtime-1:generation:7:replies",
        body_stream_id=None,
        body_chunks=(),
        background=False,
        deadline_at=None,
    )


async def _wait_for(predicate: Callable[[], bool]) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met")
