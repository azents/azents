"""Typed Agent mailbox database composition tests."""

import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionStatus,
    MailboxItemKind,
    MailboxSchedulingMode,
    SessionAgentKind,
)
from azents.engine.events.types import AgentRunState
from azents.repos.agent_mailbox import AgentMailboxRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, SessionAgent
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.mailbox.admission_data import MailboxAdmissionResult, MailboxEnqueue
from azents.repos.mailbox.data import MailboxItem
from azents.testing.types import require_instance

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
        scheduled_task_cycle_id=None,
        run_index=3,
        phase=AgentRunPhase.IDLE,
        status=status,
        parent_agent_run_id="parent-run",
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        active_tool_calls=[],
        retry_state=None,
        last_completed_event_id="event-2",
        terminal_result_event_id="event-3",
        terminal_result_message="Finished safely.",
        parent_result_delivery_state=None,
        parent_result_mailbox_item_id=None,
        parent_result_enqueued_at=None,
        stop_requested_at=None,
        created_at=_NOW,
        started_at=_NOW,
        model_call_started_at=None,
        ended_at=_NOW,
        updated_at=_NOW,
        requested_enabled_execution_options=[],
    )


class _MailboxAdmissionRepository(MailboxAdmissionRepository):
    def __init__(self) -> None:
        self.inputs: list[MailboxEnqueue] = []

    async def enqueue_in_session(
        self,
        session: AsyncSession,
        input: MailboxEnqueue,
    ) -> MailboxAdmissionResult:
        del session
        self.inputs.append(input)
        return MailboxAdmissionResult(
            mailbox_item=MailboxItem(
                id=f"buffer-{len(self.inputs)}",
                session_id=input.session_id,
                kind=input.kind,
                scheduling_mode=input.scheduling_mode,
                requested_model_target_label=input.requested_model_target_label,
                requested_reasoning_effort=input.requested_reasoning_effort,
                sender_user_id=input.sender_user_id,
                order_group=f"buffer-{len(self.inputs)}",
                order_sequence=0,
                content=input.content,
                idempotency_key=input.idempotency_key,
                metadata=input.metadata,
                action=input.action,
                attachments=input.attachments,
                file_parts=input.file_parts,
                created_at=_NOW,
                requested_enabled_execution_options=[],
            ),
            created=True,
        )


class _AgentSessionRepository(AgentSessionRepository):
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
    ) -> AgentSession:
        del session
        self.locked_session_ids.append(agent_session_id)
        return AgentSession.model_construct(
            id=agent_session_id,
            status=self.target_status,
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


def _repository(
    *,
    target_status: AgentSessionStatus = AgentSessionStatus.ACTIVE,
    target_stopping: bool = False,
) -> tuple[
    AgentMailboxRepository,
    _MailboxAdmissionRepository,
    _AgentSessionRepository,
]:
    admission = _MailboxAdmissionRepository()
    sessions = _AgentSessionRepository(
        target_status=target_status,
        target_stopping=target_stopping,
    )
    return (
        AgentMailboxRepository(
            mailbox_admission_repository=admission,
            agent_session_repository=sessions,
        ),
        admission,
        sessions,
    )


@pytest.mark.parametrize(
    ("operation", "expected_kind", "expected_mode"),
    [
        ("spawn", "spawn_agent", MailboxSchedulingMode.WAKE_SESSION),
        ("message", "send_message", MailboxSchedulingMode.QUEUE_ONLY),
        ("followup", "followup_task", MailboxSchedulingMode.WAKE_SESSION),
    ],
)
async def test_instruction_operations_own_scheduling_intent(
    operation: str,
    expected_kind: str,
    expected_mode: MailboxSchedulingMode,
) -> None:
    repository, admission, sessions = _repository()
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
        "spawn": repository.enqueue_spawn_assignment,
        "message": repository.enqueue_message,
        "followup": repository.enqueue_followup_task,
    }
    await methods[operation](
        require_instance(MagicMock(spec=AsyncSession), AsyncSession),
        source=source,
        target=target,
        content="Do the work.",
    )
    [input] = admission.inputs
    assert input.kind is MailboxItemKind.AGENT_MESSAGE
    assert input.scheduling_mode is expected_mode
    assert input.sender_user_id is None
    assert input.metadata["message_kind"] == expected_kind
    assert sessions.activity_ids == ["root-agent", "child-agent"]
    assert sessions.running_session_ids == []


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
    repository, admission, sessions = _repository()
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
    result = await repository.enqueue_terminal_result(
        require_instance(MagicMock(spec=AsyncSession), AsyncSession),
        source=source,
        target=parent,
        run=_terminal_run(status),
        content="Finished safely.",
    )
    [input] = admission.inputs
    assert result.id == "buffer-1"
    assert input.scheduling_mode is MailboxSchedulingMode.QUEUE_ONLY
    assert input.sender_user_id is None
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
    assert sessions.activity_ids == ["child-agent", "root-agent"]
    assert sessions.running_session_ids == []


async def test_terminal_result_requires_direct_parent() -> None:
    repository, admission, sessions = _repository()
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
        await repository.enqueue_terminal_result(
            require_instance(MagicMock(spec=AsyncSession), AsyncSession),
            source=source,
            target=wrong_target,
            run=_terminal_run(AgentRunStatus.COMPLETED),
            content="Finished safely.",
        )
    assert admission.inputs == []
    assert sessions.locked_session_ids == []


async def test_mailbox_rejects_archived_target_before_enqueue() -> None:
    """Archived descendants reject collaboration input and wake side effects."""
    repository, admission, sessions = _repository(
        target_status=AgentSessionStatus.ARCHIVED,
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
        await repository.enqueue_followup_task(
            require_instance(MagicMock(spec=AsyncSession), AsyncSession),
            source=source,
            target=target,
            content="Resume work.",
        )
    assert admission.inputs == []
    assert sessions.activity_ids == []
    assert sessions.running_session_ids == []


async def test_wake_mailbox_rejects_stopping_target_before_enqueue() -> None:
    """Wake-producing collaboration cannot escape an existing stop request."""
    repository, admission, sessions = _repository(target_stopping=True)
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
        await repository.enqueue_followup_task(
            require_instance(MagicMock(spec=AsyncSession), AsyncSession),
            source=source,
            target=target,
            content="Resume work.",
        )
    assert admission.inputs == []
    assert sessions.activity_ids == []
    assert sessions.running_session_ids == []
