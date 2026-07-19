"""Durable subagent terminal result delivery tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunParentResultDeliveryState,
    AgentRunPhase,
    AgentRunStatus,
    InputBufferKind,
    InputBufferSchedulingMode,
    SessionAgentKind,
)
from azents.engine.events.types import AgentRunState
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import SessionAgent
from azents.repos.input_buffer.data import InputBuffer
from azents.services.agent_mailbox import AgentMailboxService
from azents.services.subagent_terminal_result import SubagentTerminalResultService

_NOW = datetime.datetime.now(datetime.UTC)
_RUN_ID = "run-1".rjust(32, "0")
_GRANDCHILD_RUN_ID = "grandchild-run".rjust(32, "0")
_TERMINAL_STATUSES = [
    AgentRunStatus.COMPLETED,
    AgentRunStatus.FAILED,
    AgentRunStatus.STOPPED,
    AgentRunStatus.INTERRUPTED,
    AgentRunStatus.CANCELLED,
]


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


def _run(
    status: AgentRunStatus,
    *,
    run_id: str = _RUN_ID,
    session_id: str = "child-session",
    run_index: int = 1,
    message: str | None = None,
) -> AgentRunState:
    return AgentRunState(
        id=run_id,
        session_id=session_id,
        run_index=run_index,
        phase=AgentRunPhase.IDLE,
        status=status,
        parent_agent_run_id="parent-run",
        active_tool_calls=[],
        retry_state=None,
        last_completed_event_id="event-1",
        terminal_result_event_id="event-2",
        terminal_result_message=message,
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


@dataclass
class _Store:
    runs: dict[str, AgentRunState]
    agents_by_session_id: dict[str, SessionAgent]
    agents_by_id: dict[str, SessionAgent]
    descendants_by_id: dict[str, list[SessionAgent]] = field(default_factory=dict)
    committed_buffers: list[InputBuffer] = field(default_factory=list)
    rollback_count: int = 0


@dataclass
class _Transaction:
    pending_buffers: list[InputBuffer] = field(default_factory=list)
    pending_runs: dict[str, AgentRunState] = field(default_factory=dict)


class _SessionManager:
    def __init__(self, store: _Store) -> None:
        self.store = store

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[AsyncSession, None]:
        transaction = _Transaction()
        try:
            yield cast(AsyncSession, transaction)
        except Exception:
            self.store.rollback_count += 1
            raise
        else:
            self.store.committed_buffers.extend(transaction.pending_buffers)
            self.store.runs.update(transaction.pending_runs)


class _AgentRunRepository:
    def __init__(
        self,
        store: _Store,
        *,
        fail_list: bool = False,
        fail_finalize: bool = False,
    ) -> None:
        self.store = store
        self.fail_list = fail_list
        self.fail_finalize = fail_finalize
        self.locked_run_ids: list[str] = []

    async def list_parent_result_delivery_candidate_ids_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[str]:
        del session
        if self.fail_list:
            raise RuntimeError("candidate query failed")
        candidates = [
            run
            for run in self.store.runs.values()
            if run.session_id == session_id
            and run.status in _TERMINAL_STATUSES
            and run.parent_result_delivery_state is None
        ]
        return [run.id for run in sorted(candidates, key=lambda run: run.run_index)]

    async def lock_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState | None:
        del session
        self.locked_run_ids.append(run_id)
        return self.store.runs.get(run_id)

    async def mark_parent_result_enqueued(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        input_buffer_id: str,
        enqueued_at: datetime.datetime,
    ) -> AgentRunState:
        if self.fail_finalize:
            raise RuntimeError("finalization failed")
        transaction = cast(_Transaction, session)
        run = self.store.runs[run_id]
        finalized = run.model_copy(
            update={
                "parent_result_delivery_state": (
                    AgentRunParentResultDeliveryState.ENQUEUED
                ),
                "parent_result_input_buffer_id": input_buffer_id,
                "parent_result_enqueued_at": enqueued_at,
            }
        )
        transaction.pending_runs[run_id] = finalized
        return finalized


class _AgentSessionRepository:
    def __init__(self, store: _Store) -> None:
        self.store = store

    async def get_session_agent_by_session_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> SessionAgent | None:
        del session
        return self.store.agents_by_session_id.get(agent_session_id)

    async def get_session_agent_by_id(
        self,
        session: AsyncSession,
        session_agent_id: str,
    ) -> SessionAgent | None:
        del session
        return self.store.agents_by_id.get(session_agent_id)

    async def list_descendant_session_agents(
        self,
        session: AsyncSession,
        *,
        session_agent_id: str,
        include_self: bool,
    ) -> list[SessionAgent]:
        del session, include_self
        return self.store.descendants_by_id.get(session_agent_id, [])


class _AgentMailboxService:
    def __init__(self) -> None:
        self.attempts: list[tuple[str, str, str, str]] = []

    async def enqueue_terminal_result(
        self,
        session: AsyncSession,
        *,
        source: SessionAgent,
        target: SessionAgent,
        run: AgentRunState,
        content: str,
    ) -> InputBuffer:
        transaction = cast(_Transaction, session)
        self.attempts.append((source.id, target.id, run.id, content))
        buffer = InputBuffer(
            id=f"buffer-{len(self.attempts)}",
            session_id=target.agent_session_id,
            kind=InputBufferKind.AGENT_MESSAGE,
            scheduling_mode=InputBufferSchedulingMode.QUEUE_ONLY,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            actor_user_id=None,
            content=content,
            idempotency_key=f"agent_result:{run.id}",
            metadata={"message_kind": "agent_result"},
            action=None,
            attachments=[],
            file_parts=[],
            created_at=_NOW,
        )
        transaction.pending_buffers.append(buffer)
        return buffer


def _service(
    run: AgentRunState,
    *,
    fail_list: bool = False,
    fail_finalize: bool = False,
) -> tuple[
    SubagentTerminalResultService,
    _Store,
    _AgentRunRepository,
    _AgentMailboxService,
]:
    parent = _session_agent(
        id="root-agent",
        session_id="root-session",
        path="/root",
        kind=SessionAgentKind.ROOT,
        parent_id=None,
    )
    child = _session_agent(
        id="child-agent",
        session_id=run.session_id,
        path="/root/child",
        kind=SessionAgentKind.SUBAGENT,
        parent_id="root-agent",
    )
    store = _Store(
        runs={run.id: run},
        agents_by_session_id={
            parent.agent_session_id: parent,
            child.agent_session_id: child,
        },
        agents_by_id={parent.id: parent, child.id: child},
        descendants_by_id={parent.id: [child]},
    )
    run_repository = _AgentRunRepository(
        store,
        fail_list=fail_list,
        fail_finalize=fail_finalize,
    )
    mailbox_service = _AgentMailboxService()
    service = SubagentTerminalResultService(
        session_manager=cast(SessionManager[AsyncSession], _SessionManager(store)),
        agent_run_repository=cast(AgentRunRepository, run_repository),
        agent_session_repository=cast(
            AgentSessionRepository,
            _AgentSessionRepository(store),
        ),
        agent_mailbox_service=cast(AgentMailboxService, mailbox_service),
    )
    return service, store, run_repository, mailbox_service


@pytest.mark.parametrize(
    ("status", "expected_content"),
    [
        (
            AgentRunStatus.COMPLETED,
            "The agent run completed without a result message.",
        ),
        (AgentRunStatus.FAILED, "The agent run failed."),
        (AgentRunStatus.STOPPED, "The agent run was stopped."),
        (AgentRunStatus.INTERRUPTED, "The agent run was interrupted."),
        (
            AgentRunStatus.CANCELLED,
            "The agent run was cancelled before completing.",
        ),
    ],
)
async def test_delivers_every_terminal_status_to_direct_parent(
    status: AgentRunStatus,
    expected_content: str,
) -> None:
    service, store, run_repository, mailbox_service = _service(_run(status))

    summary = await service.deliver_pending_for_source_session(
        "child-session",
        repair_source="terminal_boundary",
    )

    assert summary.attempted == 1
    assert summary.enqueued == 1
    assert summary.failed == 0
    assert run_repository.locked_run_ids == [_RUN_ID]
    assert mailbox_service.attempts == [
        ("child-agent", "root-agent", _RUN_ID, expected_content)
    ]
    [buffer] = store.committed_buffers
    assert buffer.session_id == "root-session"
    assert buffer.scheduling_mode is InputBufferSchedulingMode.QUEUE_ONLY
    finalized = store.runs[_RUN_ID]
    assert (
        finalized.parent_result_delivery_state
        is AgentRunParentResultDeliveryState.ENQUEUED
    )
    assert finalized.parent_result_input_buffer_id == buffer.id
    assert finalized.parent_result_enqueued_at is not None


@pytest.mark.parametrize(
    ("message", "expected_content"),
    [
        ("Safe runtime failure.", "Safe runtime failure."),
        (
            "Model provider error: provider-private detail",
            "The agent run failed.",
        ),
    ],
)
async def test_failed_result_sanitizes_provider_details(
    message: str,
    expected_content: str,
) -> None:
    service, _store, _run_repository, mailbox_service = _service(
        _run(AgentRunStatus.FAILED, message=message),
    )

    summary = await service.deliver_pending_for_source_session(
        "child-session",
        repair_source="terminal_boundary",
    )

    assert summary.enqueued == 1
    assert mailbox_service.attempts == [
        ("child-agent", "root-agent", _RUN_ID, expected_content)
    ]


async def test_delivery_is_durable_and_idempotent_across_repair_attempts() -> None:
    service, store, run_repository, mailbox_service = _service(
        _run(AgentRunStatus.COMPLETED, message="Done."),
    )

    first = await service.deliver_pending_for_source_session(
        "child-session",
        repair_source="terminal_boundary",
    )
    second = await service.deliver_pending_for_source_session(
        "child-session",
        repair_source="source_session_reuse",
    )

    assert first.enqueued == 1
    assert second.attempted == 0
    assert run_repository.locked_run_ids == [_RUN_ID]
    assert mailbox_service.attempts == [("child-agent", "root-agent", _RUN_ID, "Done.")]
    assert len(store.committed_buffers) == 1


async def test_finalize_failure_rolls_back_buffer_and_delivery_marker() -> None:
    service, store, _run_repository, mailbox_service = _service(
        _run(AgentRunStatus.COMPLETED, message="Done."),
        fail_finalize=True,
    )

    summary = await service.deliver_pending_for_source_session(
        "child-session",
        repair_source="terminal_boundary",
    )

    assert summary.attempted == 1
    assert summary.enqueued == 0
    assert summary.failed == 1
    assert len(mailbox_service.attempts) == 1
    assert store.committed_buffers == []
    assert store.runs[_RUN_ID].parent_result_delivery_state is None
    assert store.rollback_count == 1


async def test_candidate_query_failure_is_best_effort() -> None:
    service, store, run_repository, mailbox_service = _service(
        _run(AgentRunStatus.COMPLETED, message="Done."),
        fail_list=True,
    )

    summary = await service.deliver_pending_for_source_session(
        "child-session",
        repair_source="terminal_boundary",
    )

    assert summary.attempted == 0
    assert summary.enqueued == 0
    assert summary.failed == 1
    assert run_repository.locked_run_ids == []
    assert mailbox_service.attempts == []
    assert store.committed_buffers == []
    assert store.runs[_RUN_ID].parent_result_delivery_state is None
    assert store.rollback_count == 1


async def test_parent_repair_only_scans_direct_children() -> None:
    service, store, _run_repository, mailbox_service = _service(
        _run(AgentRunStatus.COMPLETED, message="Child done."),
    )
    child = store.agents_by_id["child-agent"]
    grandchild = _session_agent(
        id="grandchild-agent",
        session_id="grandchild-session",
        path="/root/child/grandchild",
        kind=SessionAgentKind.SUBAGENT,
        parent_id=child.id,
    )
    store.agents_by_session_id[grandchild.agent_session_id] = grandchild
    store.agents_by_id[grandchild.id] = grandchild
    store.descendants_by_id["root-agent"] = [child, grandchild]
    store.runs[_GRANDCHILD_RUN_ID] = _run(
        AgentRunStatus.COMPLETED,
        run_id=_GRANDCHILD_RUN_ID,
        session_id="grandchild-session",
        message="Grandchild done.",
    )

    summary = await service.deliver_pending_for_parent_children(
        "root-session",
        repair_source="parent_wait",
    )

    assert summary.enqueued == 1
    assert mailbox_service.attempts == [
        ("child-agent", "root-agent", _RUN_ID, "Child done.")
    ]
    assert store.runs[_GRANDCHILD_RUN_ID].parent_result_delivery_state is None
