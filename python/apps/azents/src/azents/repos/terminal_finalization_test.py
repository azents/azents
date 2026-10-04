"""Atomic terminal Run, Agent mailbox, and repair repository regressions."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent_session_data import AgentSession, SessionAgent
from azents.core.enums import (
    AgentRunParentResultDeliveryState,
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionStatus,
    SessionAgentKind,
)
from azents.core.mailbox_data import MailboxItem, MailboxItemCreate
from azents.engine.events.types import AgentRunState
from azents.rdb.session_capabilities import ReadSession, ReadWriteSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_mailbox import AgentMailboxRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.subagent_terminal_result import SubagentTerminalResultRepository
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository
from azents.repos.terminal_finalization_data import TerminalDeliveryDisposition

_NOW = datetime.now(UTC)
_RUN_ID = "1" * 32


@dataclasses.dataclass
class _State:
    run: AgentRunState
    mailbox_items: list[MailboxItem]
    activity_ids: list[str]
    lock_order: list[str]
    commits: int = 0
    rollbacks: int = 0
    closed: int = 0


class _Transaction(AsyncSession):
    """Transaction-local durable state; changes publish only on normal exit."""

    def __init__(self, state: _State) -> None:
        self.run = state.run
        self.mailbox_items = list(state.mailbox_items)
        self.activity_ids = list(state.activity_ids)
        self.state = state
        self.active = True


def _transaction(session: ReadSession) -> _Transaction:
    raw = session.read_session
    assert isinstance(raw, _Transaction)
    assert raw.active
    return raw


class _SessionManager:
    def __init__(self, state: _State) -> None:
        self.state = state
        self.active: _Transaction | None = None

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        session = _Transaction(self.state)
        assert self.active is None
        self.active = session
        try:
            yield ReadWriteSession(session)
        except BaseException:
            self.state.rollbacks += 1
            raise
        else:
            self.state.run = session.run
            self.state.mailbox_items = session.mailbox_items
            self.state.activity_ids = session.activity_ids
            self.state.commits += 1
        finally:
            session.active = False
            self.active = None
            self.state.closed += 1


class _Runs(AgentRunRepository):
    def __init__(self, *, marker_failure: BaseException | None) -> None:
        self.marker_failure = marker_failure
        self.saw_mailbox_and_activity_before_failure = False

    async def get_by_id(
        self,
        session: ReadSession,
        run_id: str,
    ) -> AgentRunState | None:
        run = _transaction(session).run
        return run if run.id == run_id else None

    async def lock_by_id(
        self,
        session: WriteSession,
        run_id: str,
    ) -> AgentRunState | None:
        _transaction(session).state.lock_order.append("run")
        return await self.get_by_id(session, run_id)

    async def mark_stopped_for_user_stop(
        self,
        session: WriteSession,
        run_id: str,
        *,
        ended_at: datetime,
    ) -> AgentRunState | None:
        transaction = _transaction(session)
        if transaction.run.id != run_id:
            return None
        transaction.run = transaction.run.model_copy(
            update={
                "status": AgentRunStatus.STOPPED,
                "ended_at": ended_at,
                "terminal_result_event_id": None,
                "terminal_result_message": None,
            }
        )
        return transaction.run

    async def mark_parent_result_enqueued(
        self,
        session: WriteSession,
        *,
        run_id: str,
        mailbox_item_id: str,
        enqueued_at: datetime,
    ) -> AgentRunState:
        transaction = _transaction(session)
        assert transaction.run.id == run_id
        assert len(transaction.mailbox_items) == 1
        assert transaction.activity_ids == ["child-agent", "root-agent"]
        transaction.state.lock_order.append("delivery_marker")
        if self.marker_failure is not None:
            self.saw_mailbox_and_activity_before_failure = True
            raise self.marker_failure
        transaction.run = transaction.run.model_copy(
            update={
                "parent_result_delivery_state": (
                    AgentRunParentResultDeliveryState.ENQUEUED
                ),
                "parent_result_mailbox_item_id": mailbox_item_id,
                "parent_result_enqueued_at": enqueued_at,
            }
        )
        return transaction.run

    async def mark_parent_result_suppressed(
        self,
        session: WriteSession,
        *,
        run_id: str,
        finalized_at: datetime,
    ) -> AgentRunState:
        transaction = _transaction(session)
        assert transaction.run.id == run_id
        transaction.run = transaction.run.model_copy(
            update={
                "parent_result_delivery_state": (
                    AgentRunParentResultDeliveryState.SUPPRESSED
                ),
                "parent_result_enqueued_at": finalized_at,
            }
        )
        return transaction.run


class _Sessions(AgentSessionRepository):
    def __init__(
        self,
        *,
        source: SessionAgent,
        parent: SessionAgent,
        stop_requested: bool,
        parent_status: AgentSessionStatus,
    ) -> None:
        self.source = source
        self.parent = parent
        self.stop_requested = stop_requested
        self.parent_status = parent_status

    async def has_stop_request(
        self,
        session: ReadSession,
        session_id: str,
    ) -> bool:
        _transaction(session)
        assert session_id == self.source.agent_session_id
        return self.stop_requested

    async def get_session_agent_by_session_id(
        self,
        session: ReadSession,
        agent_session_id: str,
    ) -> SessionAgent | None:
        _transaction(session)
        return self.source if agent_session_id == self.source.agent_session_id else None

    async def get_session_agent_by_id(
        self,
        session: ReadSession,
        session_agent_id: str,
    ) -> SessionAgent | None:
        _transaction(session)
        return self.parent if session_agent_id == self.parent.id else None

    async def lock_session_agent_by_id(
        self,
        session: WriteSession,
        session_agent_id: str,
    ) -> SessionAgent | None:
        _transaction(session).state.lock_order.append("session_agent")
        return await self.get_session_agent_by_id(session, session_agent_id)

    async def lock_by_id(
        self,
        session: WriteSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        transaction = _transaction(session)
        transaction.state.lock_order.append("parent_session")
        if agent_session_id != self.parent.agent_session_id:
            return None
        return AgentSession.model_construct(
            id=agent_session_id,
            status=self.parent_status,
            stop_requested_at=None,
        )

    async def get_by_id(
        self,
        session: ReadSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        _transaction(session)
        if agent_session_id != self.parent.agent_session_id:
            return None
        return AgentSession.model_construct(
            id=agent_session_id,
            status=self.parent_status,
            stop_requested_at=None,
        )

    async def fence_active_mailbox_target(
        self,
        session: WriteSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        _transaction(session).state.lock_order.append("target_admission")
        current = await self.get_by_id(session, agent_session_id)
        if current is None or current.status is not AgentSessionStatus.ACTIVE:
            return None
        return current

    async def mark_session_agent_message_activity(
        self,
        session: WriteSession,
        *,
        session_agent_id: str,
    ) -> None:
        _transaction(session).activity_ids.append(session_agent_id)


class _Mailbox(MailboxRepository):
    async def get_by_idempotency_key(
        self,
        session: ReadSession,
        *,
        session_id: str,
        kind: object,
        idempotency_key: str,
    ) -> MailboxItem | None:
        return next(
            (
                item
                for item in _transaction(session).mailbox_items
                if item.session_id == session_id
                and item.kind == kind
                and item.idempotency_key == idempotency_key
            ),
            None,
        )

    async def create_idempotent(
        self,
        session: WriteSession,
        create: MailboxItemCreate,
        *,
        idempotency_key: str,
    ) -> MailboxItem:
        transaction = _transaction(session)
        assert create.idempotency_key == idempotency_key
        mailbox_item = MailboxItem(
            id="2" * 32,
            session_id=create.session_id,
            kind=create.kind,
            scheduling_mode=create.scheduling_mode,
            requested_model_target_label=create.requested_model_target_label,
            requested_reasoning_effort=create.requested_reasoning_effort,
            requested_enabled_execution_options=create.requested_enabled_execution_options,
            sender_user_id=create.sender_user_id,
            order_group=create.order_group or "2" * 32,
            order_sequence=create.order_sequence,
            content=create.content,
            idempotency_key=idempotency_key,
            metadata=create.metadata,
            action=create.action,
            attachments=create.attachments,
            file_parts=create.file_parts,
            created_at=_NOW,
        )
        transaction.mailbox_items.append(mailbox_item)
        transaction.state.lock_order.append("mailbox")
        return mailbox_item


@dataclasses.dataclass(frozen=True)
class _Fixture:
    terminal: TerminalRunFinalizationRepository
    repair: SubagentTerminalResultRepository
    manager: _SessionManager
    state: _State
    runs: _Runs


def _fixture(
    *,
    status: AgentRunStatus,
    stop_requested: bool,
    message: str | None,
    parent_id: str | None,
    parent_status: AgentSessionStatus,
    marker_failure: BaseException | None,
) -> _Fixture:
    parent = SessionAgent(
        id="root-agent",
        context_id="context-001",
        root_session_agent_id="root-agent",
        agent_session_id="root-session",
        kind=SessionAgentKind.ROOT,
        name="root",
        path="/root",
        agent_type="default",
        parent_session_agent_id=None,
        last_task_message=None,
        last_message_at=None,
        parent_observed_run_index=None,
        parent_observed_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    source = parent.model_copy(
        update={
            "id": "child-agent",
            "agent_session_id": "child-session",
            "kind": SessionAgentKind.SUBAGENT,
            "name": "child",
            "path": "/root/child",
            "parent_session_agent_id": parent_id,
        }
    )
    state = _State(
        run=AgentRunState(
            id=_RUN_ID,
            session_id=source.agent_session_id,
            scheduled_task_cycle_id=None,
            run_index=1,
            phase=AgentRunPhase.IDLE,
            status=status,
            parent_agent_run_id=None,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            requested_enabled_execution_options=[],
            terminal_result_event_id="3" * 32,
            terminal_result_message=message,
            parent_result_delivery_state=None,
            parent_result_mailbox_item_id=None,
            parent_result_enqueued_at=None,
            created_at=_NOW,
            started_at=_NOW,
            model_call_started_at=None,
            ended_at=_NOW,
            updated_at=_NOW,
        ),
        mailbox_items=[],
        activity_ids=[],
        lock_order=[],
    )
    manager = _SessionManager(state)
    sessions = _Sessions(
        source=source,
        parent=parent,
        stop_requested=stop_requested,
        parent_status=parent_status,
    )
    runs = _Runs(marker_failure=marker_failure)
    agent_mailbox = AgentMailboxRepository(
        mailbox_admission_repository=MailboxAdmissionRepository(
            session_manager=manager,
            mailbox_item_repository=_Mailbox(),
            agent_session_repository=sessions,
        ),
        agent_session_repository=sessions,
    )
    return _Fixture(
        terminal=TerminalRunFinalizationRepository(
            session_manager=manager,
            agent_run_repository=runs,
            agent_session_repository=sessions,
            agent_mailbox_repository=agent_mailbox,
        ),
        repair=SubagentTerminalResultRepository(
            session_manager=manager,
            agent_run_repository=runs,
            agent_session_repository=sessions,
            agent_mailbox_repository=agent_mailbox,
        ),
        manager=manager,
        state=state,
        runs=runs,
    )


async def test_user_stop_converges_interrupted_run_before_parent_delivery() -> None:
    """User Stop, mailbox, activity and marker share one completed transaction."""
    fixture = _fixture(
        status=AgentRunStatus.INTERRUPTED,
        stop_requested=True,
        message="partial output",
        parent_id="root-agent",
        parent_status=AgentSessionStatus.ACTIVE,
        marker_failure=None,
    )
    outcome = await fixture.terminal.finalize_run(_RUN_ID)
    assert outcome.disposition is TerminalDeliveryDisposition.ENQUEUED
    assert fixture.state.lock_order == [
        "run",
        "run",
        "target_admission",
        "target_admission",
        "mailbox",
        "delivery_marker",
    ]
    assert fixture.state.run.status is AgentRunStatus.STOPPED
    assert fixture.state.run.terminal_result_event_id is None
    assert fixture.state.run.terminal_result_message is None
    assert fixture.state.mailbox_items[0].content == "The agent run was stopped."
    assert fixture.state.activity_ids == ["child-agent", "root-agent"]
    assert fixture.state.commits == 1
    assert fixture.state.closed == 1
    assert fixture.manager.active is None


async def test_terminal_completion_is_closed_and_idempotent() -> None:
    fixture = _fixture(
        status=AgentRunStatus.COMPLETED,
        stop_requested=False,
        message=" Done. ",
        parent_id="root-agent",
        parent_status=AgentSessionStatus.ACTIVE,
        marker_failure=None,
    )
    first = await fixture.terminal.finalize_run(_RUN_ID)
    assert fixture.manager.active is None
    second = await fixture.terminal.finalize_run(_RUN_ID)
    assert second.disposition is TerminalDeliveryDisposition.ALREADY_FINALIZED
    assert second.mailbox_item_id == first.mailbox_item_id
    assert len(fixture.state.mailbox_items) == 1
    assert fixture.state.mailbox_items[0].content == "Done."
    assert fixture.state.mailbox_items[0].idempotency_key == f"agent_result:{_RUN_ID}"
    assert fixture.state.activity_ids == ["child-agent", "root-agent"]
    assert fixture.state.commits == 2
    assert fixture.state.closed == 2
    assert fixture.manager.active is None


@pytest.mark.parametrize("cancelled", [False, True])
async def test_enqueue_failure_rolls_back_run_mailbox_activity_and_marker(
    cancelled: bool,
) -> None:
    failure = asyncio.CancelledError() if cancelled else RuntimeError("marker failed")
    fixture = _fixture(
        status=AgentRunStatus.INTERRUPTED,
        stop_requested=True,
        message="partial output",
        parent_id="root-agent",
        parent_status=AgentSessionStatus.ACTIVE,
        marker_failure=failure,
    )
    expected = asyncio.CancelledError if cancelled else RuntimeError
    with pytest.raises(expected):
        await fixture.terminal.finalize_run(_RUN_ID)
    assert fixture.runs.saw_mailbox_and_activity_before_failure
    assert fixture.state.run.status is AgentRunStatus.INTERRUPTED
    assert fixture.state.run.terminal_result_message == "partial output"
    assert fixture.state.run.parent_result_delivery_state is None
    assert fixture.state.mailbox_items == []
    assert fixture.state.activity_ids == []
    assert fixture.state.commits == 0
    assert fixture.state.rollbacks == 1
    assert fixture.state.closed == 1
    assert fixture.manager.active is None


@pytest.mark.parametrize(
    ("parent_id", "message"),
    [
        (None, "Subagent has no direct parent"),
        ("missing-parent", "Direct parent SessionAgent not found"),
    ],
)
async def test_repair_parent_failure_preserves_coordinator_suppression_difference(
    parent_id: str | None,
    message: str,
) -> None:
    coordinator = _fixture(
        status=AgentRunStatus.COMPLETED,
        stop_requested=False,
        message="Done.",
        parent_id=parent_id,
        parent_status=AgentSessionStatus.ACTIVE,
        marker_failure=None,
    )
    outcome = await coordinator.terminal.finalize_run(_RUN_ID)
    assert outcome.disposition is TerminalDeliveryDisposition.SUPPRESSED
    assert coordinator.state.run.parent_result_delivery_state is (
        AgentRunParentResultDeliveryState.SUPPRESSED
    )
    repair = _fixture(
        status=AgentRunStatus.COMPLETED,
        stop_requested=False,
        message="Done.",
        parent_id=parent_id,
        parent_status=AgentSessionStatus.ACTIVE,
        marker_failure=None,
    )
    with pytest.raises(ValueError, match=message):
        await repair.repair.deliver_one(_RUN_ID)
    assert repair.state.run.parent_result_delivery_state is None
    assert repair.state.mailbox_items == []
    assert repair.state.rollbacks == 1
    assert repair.manager.active is None


async def test_repair_archived_parent_failure_does_not_become_suppression() -> None:
    fixture = _fixture(
        status=AgentRunStatus.COMPLETED,
        stop_requested=False,
        message="Done.",
        parent_id="root-agent",
        parent_status=AgentSessionStatus.ARCHIVED,
        marker_failure=None,
    )
    with pytest.raises(ValueError, match="Target AgentSession is not active"):
        await fixture.repair.deliver_one(_RUN_ID)
    assert fixture.state.run.parent_result_delivery_state is None
    assert fixture.state.mailbox_items == []
    assert fixture.state.activity_ids == []
    assert fixture.manager.active is None
    outcome = await fixture.terminal.finalize_run(_RUN_ID)
    assert outcome.disposition is TerminalDeliveryDisposition.SUPPRESSED
