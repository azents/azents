"""Typed agent mailbox service tests."""

import datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionStatus,
    InputBufferKind,
    InputBufferSchedulingMode,
    SessionAgentKind,
)
from azents.engine.events.types import AgentRunState
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import SessionAgent
from azents.repos.input_buffer.data import InputBuffer
from azents.services.agent_mailbox import AgentMailboxService
from azents.services.input_buffer import (
    InputBufferEnqueue,
    InputBufferEnqueueResult,
    InputBufferService,
)

_NOW = datetime.datetime.now(datetime.UTC)
_RUN_ID = "run-1".rjust(32, "0")


def _session_agent(
    *,
    id: str,
    session_id: str,
    path: str,
    kind: SessionAgentKind,
    parent_id: str | None,
) -> SessionAgent:
    return SessionAgent(
        id=id,
        context_id="context-1",
        root_session_agent_id="root-agent",
        agent_session_id=session_id,
        kind=kind,
        name=path.rsplit("/", 1)[-1],
        path=path,
        agent_type="default",
        parent_session_agent_id=parent_id,
        last_task_message=None,
        last_message_at=None,
        parent_observed_run_index=None,
        parent_observed_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _terminal_run(status: AgentRunStatus) -> AgentRunState:
    return AgentRunState(
        id=_RUN_ID,
        session_id="child-session",
        run_index=3,
        phase=AgentRunPhase.IDLE,
        status=status,
        parent_agent_run_id="parent-run",
        active_tool_calls=[],
        retry_state=None,
        last_completed_event_id="event-2",
        terminal_result_event_id="event-3",
        terminal_result_message="Finished safely.",
        parent_result_delivery_state=None,
        parent_result_input_buffer_id=None,
        parent_result_enqueued_at=None,
        stop_requested_at=None,
        created_at=_NOW,
        started_at=_NOW,
        model_call_started_at=None,
        ended_at=_NOW,
        updated_at=_NOW,
    )


class _InputBufferService:
    def __init__(self) -> None:
        self.inputs: list[InputBufferEnqueue] = []

    async def enqueue(
        self,
        session: AsyncSession,
        input: InputBufferEnqueue,
    ) -> InputBufferEnqueueResult:
        del session
        self.inputs.append(input)
        return InputBufferEnqueueResult(
            input_buffer=InputBuffer(
                id=f"buffer-{len(self.inputs)}",
                session_id=input.session_id,
                kind=input.kind,
                scheduling_mode=input.scheduling_mode,
                requested_model_target_label=input.requested_model_target_label,
                requested_reasoning_effort=input.requested_reasoning_effort,
                actor_user_id=input.actor_user_id,
                content=input.content,
                idempotency_key=input.idempotency_key,
                metadata=input.metadata,
                action=input.action,
                attachments=input.attachments,
                file_parts=input.file_parts,
                created_at=_NOW,
            ),
            created=True,
        )


class _LockedAgentSession:
    def __init__(
        self,
        status: AgentSessionStatus,
        *,
        stop_requested_at: datetime.datetime | None,
    ) -> None:
        self.status = status
        self.stop_requested_at = stop_requested_at


class _AgentSessionRepository:
    def __init__(
        self,
        *,
        target_status: AgentSessionStatus = AgentSessionStatus.ACTIVE,
        target_stopping: bool = False,
    ) -> None:
        self.activity_ids: list[str] = []
        self.running_session_ids: list[str] = []
        self.locked_session_ids: list[str] = []
        self.locked_session_agent_ids: list[str] = []
        self.target_status = target_status
        self.target_stopping = target_stopping

    async def lock_session_agent_by_id(
        self,
        session: AsyncSession,
        session_agent_id: str,
    ) -> SessionAgent:
        del session
        self.locked_session_agent_ids.append(session_agent_id)
        return _session_agent(
            id="root-agent",
            session_id="root-session",
            path="/root",
            kind=SessionAgentKind.ROOT,
            parent_id=None,
        )

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> _LockedAgentSession:
        del session
        self.locked_session_ids.append(agent_session_id)
        return _LockedAgentSession(
            self.target_status,
            stop_requested_at=_NOW if self.target_stopping else None,
        )

    async def mark_session_agent_message_activity(
        self,
        session: AsyncSession,
        *,
        session_agent_id: str,
    ) -> None:
        del session
        self.activity_ids.append(session_agent_id)

    async def mark_running_for_input_wakeup(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> None:
        del session
        self.running_session_ids.append(session_id)


def _service(
    *,
    target_status: AgentSessionStatus = AgentSessionStatus.ACTIVE,
    target_stopping: bool = False,
) -> tuple[
    AgentMailboxService,
    _InputBufferService,
    _AgentSessionRepository,
]:
    input_buffer_service = _InputBufferService()
    agent_session_repository = _AgentSessionRepository(
        target_status=target_status,
        target_stopping=target_stopping,
    )
    return (
        AgentMailboxService(
            input_buffer_service=cast(InputBufferService, input_buffer_service),
            agent_session_repository=cast(
                AgentSessionRepository,
                agent_session_repository,
            ),
        ),
        input_buffer_service,
        agent_session_repository,
    )


@pytest.mark.parametrize(
    ("operation", "expected_kind", "expected_mode", "wakes"),
    [
        ("spawn", "spawn_agent", InputBufferSchedulingMode.WAKE_SESSION, True),
        ("message", "send_message", InputBufferSchedulingMode.QUEUE_ONLY, False),
        ("followup", "followup_task", InputBufferSchedulingMode.WAKE_SESSION, True),
    ],
)
async def test_instruction_operations_own_scheduling_intent(
    operation: str,
    expected_kind: str,
    expected_mode: InputBufferSchedulingMode,
    wakes: bool,
) -> None:
    service, input_service, session_repository = _service()
    source = _session_agent(
        id="root-agent",
        session_id="root-session",
        path="/root",
        kind=SessionAgentKind.ROOT,
        parent_id=None,
    )
    target = _session_agent(
        id="child-agent",
        session_id="child-session",
        path="/root/child",
        kind=SessionAgentKind.SUBAGENT,
        parent_id="root-agent",
    )
    methods: dict[str, Any] = {
        "spawn": service.enqueue_spawn_assignment,
        "message": service.enqueue_message,
        "followup": service.enqueue_followup_task,
    }

    await methods[operation](
        cast(AsyncSession, object()),
        source=source,
        target=target,
        content="Do the work.",
        actor_user_id="user-1",
    )

    [input] = input_service.inputs
    assert input.kind is InputBufferKind.AGENT_MESSAGE
    assert input.scheduling_mode is expected_mode
    assert input.metadata["message_kind"] == expected_kind
    assert session_repository.activity_ids == ["root-agent", "child-agent"]
    assert session_repository.running_session_ids == (
        ["child-session"] if wakes else []
    )


@pytest.mark.parametrize(
    "status",
    [
        AgentRunStatus.COMPLETED,
        AgentRunStatus.FAILED,
        AgentRunStatus.STOPPED,
        AgentRunStatus.INTERRUPTED,
        AgentRunStatus.CANCELLED,
    ],
)
async def test_terminal_result_is_queue_only_and_contains_run_metadata(
    status: AgentRunStatus,
) -> None:
    service, input_service, session_repository = _service()
    parent = _session_agent(
        id="root-agent",
        session_id="root-session",
        path="/root",
        kind=SessionAgentKind.ROOT,
        parent_id=None,
    )
    source = _session_agent(
        id="child-agent",
        session_id="child-session",
        path="/root/child",
        kind=SessionAgentKind.SUBAGENT,
        parent_id="root-agent",
    )

    result = await service.enqueue_terminal_result(
        cast(AsyncSession, object()),
        source=source,
        target=parent,
        run=_terminal_run(status),
        content="Finished safely.",
    )

    [input] = input_service.inputs
    assert result.id == "buffer-1"
    assert input.scheduling_mode is InputBufferSchedulingMode.QUEUE_ONLY
    assert input.actor_user_id is None
    assert input.idempotency_key == f"agent_result:{_RUN_ID}"
    assert input.metadata == {
        "source": "agent_mailbox",
        "message_kind": "agent_result",
        "source_session_agent_id": "child-agent",
        "source_path": "/root/child",
        "target_session_agent_id": "root-agent",
        "target_path": "/root",
        "source_run_id": _RUN_ID,
        "source_run_index": "3",
        "run_status": status.value,
        "source_terminal_result_event_id": "event-3",
    }
    assert session_repository.activity_ids == ["child-agent", "root-agent"]
    assert session_repository.running_session_ids == []


async def test_terminal_result_requires_direct_parent() -> None:
    service, input_service, session_repository = _service()
    source = _session_agent(
        id="child-agent",
        session_id="child-session",
        path="/root/child",
        kind=SessionAgentKind.SUBAGENT,
        parent_id="root-agent",
    )
    wrong_target = _session_agent(
        id="sibling-agent",
        session_id="sibling-session",
        path="/root/sibling",
        kind=SessionAgentKind.SUBAGENT,
        parent_id="root-agent",
    )

    with pytest.raises(ValueError, match="direct parent"):
        await service.enqueue_terminal_result(
            cast(AsyncSession, object()),
            source=source,
            target=wrong_target,
            run=_terminal_run(AgentRunStatus.COMPLETED),
            content="Finished safely.",
        )

    assert input_service.inputs == []
    assert session_repository.locked_session_ids == []


async def test_mailbox_rejects_archived_target_before_enqueue() -> None:
    """Archived descendants reject collaboration input and wake side effects."""
    service, input_service, session_repository = _service(
        target_status=AgentSessionStatus.ARCHIVED
    )
    source = _session_agent(
        id="root-agent",
        session_id="root-session",
        path="/root",
        kind=SessionAgentKind.ROOT,
        parent_id=None,
    )
    target = _session_agent(
        id="child-agent",
        session_id="child-session",
        path="/root/child",
        kind=SessionAgentKind.SUBAGENT,
        parent_id="root-agent",
    )

    with pytest.raises(ValueError, match="Target AgentSession is not active"):
        await service.enqueue_followup_task(
            cast(AsyncSession, object()),
            source=source,
            target=target,
            content="Resume work.",
            actor_user_id="user-1",
        )

    assert input_service.inputs == []
    assert session_repository.activity_ids == []
    assert session_repository.running_session_ids == []


async def test_wake_mailbox_rejects_stopping_target_before_enqueue() -> None:
    """Wake-producing collaboration cannot escape an existing stop request."""
    service, input_service, session_repository = _service(target_stopping=True)
    source = _session_agent(
        id="root-agent",
        session_id="root-session",
        path="/root",
        kind=SessionAgentKind.ROOT,
        parent_id=None,
    )
    target = _session_agent(
        id="child-agent",
        session_id="child-session",
        path="/root/child",
        kind=SessionAgentKind.SUBAGENT,
        parent_id="root-agent",
    )

    with pytest.raises(ValueError, match="Target AgentSession is stopping"):
        await service.enqueue_followup_task(
            cast(AsyncSession, object()),
            source=source,
            target=target,
            content="Resume work.",
            actor_user_id="user-1",
        )

    assert input_service.inputs == []
    assert session_repository.activity_ids == []
    assert session_repository.running_session_ids == []
