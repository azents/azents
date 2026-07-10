"""Background Runtime operation completion publisher tests."""

from datetime import datetime, timedelta, timezone

import pytest

from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeProtocolCapabilities,
    RuntimeRunnerOperation,
    RuntimeRunnerRegistration,
)
from azents.runtime.control_protocol.runner_operations import (
    runner_reply_target,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeBackgroundOperationContext,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
)
from azents.runtime.coordination.memory import (
    InMemoryRuntimeCoordinationStore,
)
from azents.worker.input.background_completion_publisher import (
    BackgroundCompletionPublisherConfig,
    RuntimeBackgroundCompletionPublisher,
)
from azents.worker.input.queue import InMemoryWorkerInputQueue


@pytest.mark.asyncio
async def test_background_completion_is_published_once_to_worker_input_queue() -> None:
    """Final background operations are converted to Worker input exactly once."""
    store = InMemoryRuntimeCoordinationStore()
    control = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "req-1",
    )
    runner = await control.register_runner(_runner_registration(), registered_at=_now())
    dispatch = await control.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=runner.generation,
            operation_type="bash",
            owner_session_id=None,
            payload={"command": "echo ok", "timeout_seconds": 30, "env": None},
            deadline_at=_now() + timedelta(seconds=30),
            body_stream_id=None,
            background=True,
            background_context=RuntimeBackgroundOperationContext(
                task_id="task-1",
                agent_id="agent-1",
                parent_session_id="session-1",
                workspace_id="workspace-1",
                tool_name="shell",
                idempotency_key="runtime-operation:req-1",
            ),
        ),
        created_at=_now(),
    )
    assert isinstance(dispatch, RuntimeDispatchResult)
    await control.append_reply_event(
        _event(
            request_id="req-other",
            generation=runner.generation,
            event_type=RuntimeReplyEventType.STDOUT,
            payload={"text": "ignore\n"},
        ),
        reply_stream_id=dispatch.reply_stream_id,
        operation_id=None,
        expected_target=runner_reply_target(),
        expected_subject_id="runtime-1",
    )
    await control.append_reply_event(
        _event(
            request_id=dispatch.request_id,
            generation=runner.generation,
            event_type=RuntimeReplyEventType.STDOUT,
            payload={"text": "ok\n"},
        ),
        reply_stream_id=dispatch.reply_stream_id,
        operation_id=dispatch.operation_id,
        expected_target=runner_reply_target(),
        expected_subject_id="runtime-1",
    )
    await control.append_reply_event(
        _event(
            request_id=dispatch.request_id,
            generation=runner.generation,
            event_type=RuntimeReplyEventType.FINAL_SUCCESS,
            payload={"exit_code": 0},
            final=True,
        ),
        reply_stream_id=dispatch.reply_stream_id,
        operation_id=dispatch.operation_id,
        expected_target=runner_reply_target(),
        expected_subject_id="runtime-1",
    )
    queue = InMemoryWorkerInputQueue()
    publisher = RuntimeBackgroundCompletionPublisher(
        coordination_store=store,
        worker_input_queue=queue,
        config=BackgroundCompletionPublisherConfig(claimant_id="control-a"),
    )

    assert await publisher.publish_once() == 1
    assert await publisher.publish_once() == 0
    assert len(queue.messages) == 1
    message = queue.messages[0]
    assert message.parent_session_id == "session-1"
    assert message.status == "completed"
    assert message.idempotency_key == "runtime-operation:req-1"
    assert "ok" in message.text
    assert "ignore" not in message.text


def _runner_registration() -> RuntimeRunnerRegistration:
    return RuntimeRunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version="2026-05-25",
        capabilities=RuntimeProtocolCapabilities(("bash",)),
        health="ok",
        workspace_path="/workspace/agent",
        metadata={},
        auth_credential_id="credential-1",
        connection_id="runner-connection-1",
        owner_replica_id="control-a",
    )


def _event(
    *,
    request_id: str,
    generation: int,
    event_type: RuntimeReplyEventType,
    payload: dict[str, JsonValue],
    final: bool = False,
) -> RuntimeReplyEvent:
    return RuntimeReplyEvent(
        request_id=request_id,
        runtime_id="runtime-1",
        generation=generation,
        event_type=event_type,
        payload=payload,
        created_at=_now(),
        final=final,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
