"""Native PostgreSQL claim fencing and atomic Scheduled Task admission tests."""

import datetime
from dataclasses import dataclass
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import ScheduledTaskScheduleType
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.scheduled_task import RDBScheduledTask
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_only_session_manager,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.data import ScheduledTask, ScheduledTaskCreate
from azents.repos.scheduled_task.definition import RDBScheduledTaskAuthorityValidator
from azents.repos.scheduled_task.dispatch import ScheduledTaskDispatchRepository
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.workspace import WorkspaceRepository
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)

_NOW = datetime.datetime(2026, 10, 5, tzinfo=datetime.UTC)


@dataclass(frozen=True)
class _Fixture:
    operations: ScheduledTaskDispatchRepository
    task: ScheduledTask


async def _fixture(manager: SessionManager[WriteSession]) -> _Fixture:
    """Seed native database authorities without provider or Runtime effects."""
    tag = uuid4().hex
    async with manager() as session:
        await WorkspaceRepository().create(
            session, WorkspaceCreate(name="Scheduled test", handle=f"scheduled-{tag}")
        )
        workspace_id = await WorkspaceRepository().resolve_id(
            session, f"scheduled-{tag}"
        )
        assert workspace_id is not None
        selection = make_test_model_selection_dict()
        agent = RDBAgent(
            workspace_id=workspace_id,
            name="Scheduled test Agent",
            model_selection=selection,
            lightweight_model_selection=selection,
            selectable_model_options=make_test_selectable_model_option_dicts(
                model_selection=selection, lightweight_model_selection=selection
            ),
            main_model_label="default",
            lightweight_model_label="lightweight",
        )
        session.write_session.add(agent)
        await session.write_session.flush()
        target = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                session, workspace_id=workspace_id, agent_id=agent.id
            )
        ).session
        task = await ScheduledTaskRepository().create(
            session,
            ScheduledTaskCreate(
                workspace_id=workspace_id,
                agent_id=agent.id,
                session_id=target.id,
                title="Native scheduled task",
                objective="Retain atomic admission.",
                schedule_type=ScheduledTaskScheduleType.ONCE,
                next_eligible_at=_NOW,
                binding_id=None,
                scheduled_at=_NOW,
                cron_expression=None,
                timezone=None,
            ),
        )
    return _Fixture(
        operations=ScheduledTaskDispatchRepository(
            session_manager=manager,
            agent_session_repository=AgentSessionRepository(),
            cycle_repository=ScheduledTaskCycleRepository(ToolkitStateRepository()),
            mailbox_repository=MailboxRepository(),
            authority_validator=RDBScheduledTaskAuthorityValidator(),
            task_repository=ScheduledTaskRepository(),
            clock=lambda: _NOW,
            lease_duration=datetime.timedelta(minutes=1),
        ),
        task=task,
    )


async def test_native_claim_rejects_same_owner_reclaimed_token(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A renewed lease invalidates the previous token even for the same owner."""
    fixture = await _fixture(rdb_session_manager)
    first = await fixture.operations.claim_due(now=_NOW, lease_owner="same-owner")
    assert first is not None and first.lease_until is not None
    later = _NOW + datetime.timedelta(minutes=2)
    second = await fixture.operations.claim_due(now=later, lease_owner="same-owner")
    assert second is not None and second.lease_until != first.lease_until
    with pytest.raises(RuntimeError, match="claim fence was lost"):
        await fixture.operations.admit_claimed(
            task_id=first.id,
            lease_owner="same-owner",
            lease_token=first.lease_until,
            now=later,
            controlled_now=later,
        )
    async with rdb_session_manager() as session:
        task = await ScheduledTaskRepository().get_by_id(session, first.id)
        assert task is not None and task.active_cycle_id is None
        assert task.lease_until == second.lease_until
        assert (
            await MailboxRepository().list_by_session_id(session, first.session_id)
            == []
        )


async def test_native_admission_rolls_back_cycle_mailbox_and_session_write_on_lost_cas(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Expired final lease CAS rolls back every staged admission database effect."""
    fixture = await _fixture(rdb_session_manager)
    claimed = await fixture.operations.claim_due(now=_NOW, lease_owner="scheduler")
    assert claimed is not None and claimed.lease_until is not None
    async with rdb_session_manager() as session:
        before_state = await session.read_session.scalar(
            sa.select(RDBAgentSession.run_state).where(
                RDBAgentSession.id == claimed.session_id
            )
        )
    fixture.operations.clock = lambda: _NOW + datetime.timedelta(minutes=2)
    with pytest.raises(RuntimeError, match="claim fence was lost"):
        await fixture.operations.admit_claimed(
            task_id=claimed.id,
            lease_owner="scheduler",
            lease_token=claimed.lease_until,
            now=_NOW,
            controlled_now=None,
        )
    async with rdb_session_manager() as session:
        task = await ScheduledTaskRepository().get_by_id(session, claimed.id)
        assert task is not None and task.active_cycle_id is None
        assert task.lease_until == claimed.lease_until
        assert (
            await session.read_session.scalar(
                sa.select(RDBAgentSession.run_state).where(
                    RDBAgentSession.id == claimed.session_id
                )
            )
            == before_state
        )
        assert (
            await MailboxRepository().list_by_session_id(session, claimed.session_id)
            == []
        )
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBToolkitState)
                .where(
                    RDBToolkitState.session_id == claimed.session_id,
                    RDBToolkitState.toolkit_namespace == "scheduled",
                )
            )
            == 0
        )


async def test_native_admission_publishes_exactly_one_cycle_and_mailbox(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Completed admission commits cycle, mailbox and Task cursor together."""
    fixture = await _fixture(rdb_session_manager)
    claimed = await fixture.operations.claim_due(now=_NOW, lease_owner="scheduler")
    assert claimed is not None and claimed.lease_until is not None
    result = await fixture.operations.admit_claimed(
        task_id=claimed.id,
        lease_owner="scheduler",
        lease_token=claimed.lease_until,
        now=_NOW,
        controlled_now=_NOW,
    )
    assert result.admitted
    async with rdb_session_manager() as session:
        task = await ScheduledTaskRepository().get_by_id(session, claimed.id)
        assert task is not None and task.active_cycle_id is not None
        assert task.lease_owner is None and task.lease_until is None
        mail = await MailboxRepository().list_by_session_id(session, claimed.session_id)
        assert len(mail) == 1
        assert (
            mail[0].idempotency_key == f"scheduled-task-trigger:{task.active_cycle_id}"
        )
        cycle = await fixture.operations.cycle_repository.get(
            session,
            agent_id=claimed.agent_id,
            session_id=claimed.session_id,
            cycle_id=task.active_cycle_id,
        )
        assert cycle is not None and cycle.state.phase == "admitted"


async def test_native_read_only_connection_rejects_scheduled_row_locks(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Independent PostgreSQL read scopes are enforced below typed capability checks."""
    reads = create_read_only_session_manager(rdb_engine)
    async with reads() as session:
        assert (
            await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
            == "on"
        )
    with pytest.raises(DBAPIError):
        async with reads() as session:
            await session.read_session.execute(
                sa.select(RDBScheduledTask).with_for_update()
            )
