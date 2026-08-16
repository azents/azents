"""Scheduled Task lifecycle repository tests."""

import datetime
from dataclasses import dataclass
from typing import cast

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionProductMode,
    LLMProvider,
    MailboxItemKind,
    MailboxSchedulingMode,
    ScheduledTaskScheduleType,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.mailbox_item import RDBMailboxItem
from azents.rdb.models.scheduled_task import RDBScheduledTask
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import MailboxItemCreate
from azents.repos.scheduled_task.data import ScheduledTaskCreate
from azents.repos.scheduled_task.lifecycle import ScheduledTaskLifecycleRepository
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import (
    ScheduledTaskCycleRecord,
    ScheduledTaskCycleRepository,
    ScheduledTaskCycleSnapshot,
)
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

_NOW = datetime.datetime(2026, 8, 16, 0, 0, tzinfo=datetime.UTC)


@dataclass(frozen=True)
class _Subject:
    """Complete Session authority fixture."""

    workspace_id: str
    agent_id: str
    session_id: str


@dataclass(frozen=True)
class _TaskCycle:
    """Task, cycle, trigger, and optional Run identities."""

    task_id: str
    cycle: ScheduledTaskCycleRecord
    trigger_id: str
    run_id: str | None


class _BindingFenceSession:
    """Return a re-bound Task at the final lifecycle lock."""

    def __init__(self, locked_task: RDBScheduledTask) -> None:
        self.locked_task = locked_task
        self.deleted: list[object] = []
        self.flushed = False

    async def scalar(self, query: object) -> RDBScheduledTask:
        """Return the Task visible at the final lock boundary."""
        del query
        return self.locked_task

    async def delete(self, row: object) -> None:
        """Record unexpected deletion."""
        self.deleted.append(row)

    async def flush(self) -> None:
        """Record lifecycle completion."""
        self.flushed = True


def _rdb_task(*, binding_id: str) -> RDBScheduledTask:
    """Build one detached Task row for binding-fence tests."""
    task = RDBScheduledTask(
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        title="Daily report",
        objective="Prepare the report.",
        schedule_type=ScheduledTaskScheduleType.ONCE,
        next_eligible_at=_NOW,
        binding_id=binding_id,
        scheduled_at=_NOW,
        cron_expression=None,
        timezone=None,
    )
    task.id = "t" * 32
    task.created_at = _NOW
    task.updated_at = _NOW
    return task


async def _create_subject(session: AsyncSession, *, handle: str) -> _Subject:
    """Create a complete root Session authority fixture."""
    workspace_repository = WorkspaceRepository()
    workspace_result = await workspace_repository.create(
        session,
        WorkspaceCreate(name="Scheduled lifecycle test", handle=handle),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await workspace_repository.resolve_id(session, handle)
    assert workspace_id is not None

    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{handle}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Scheduled lifecycle test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{handle}-model",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{handle}-model",
        ),
    )
    session.add(agent)
    await session.flush()
    created = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
            agent_id=agent.id,
            title=None,
        ),
    )
    return _Subject(
        workspace_id=workspace_id,
        agent_id=agent.id,
        session_id=created.id,
    )


async def _create_task_cycle(
    session: AsyncSession,
    *,
    subject: _Subject,
    title: str,
    started: bool,
) -> _TaskCycle:
    """Create one Task with an admitted or started active cycle."""
    cycle_id = uuid7().hex
    task = await ScheduledTaskRepository().create(
        session,
        ScheduledTaskCreate(
            workspace_id=subject.workspace_id,
            agent_id=subject.agent_id,
            session_id=subject.session_id,
            title=title,
            objective=f"Run {title}.",
            schedule_type=ScheduledTaskScheduleType.ONCE,
            next_eligible_at=_NOW,
            binding_id=None,
            scheduled_at=_NOW,
            cron_expression=None,
            timezone=None,
        ),
    )
    task_row = await session.get(RDBScheduledTask, task.id)
    assert task_row is not None
    task_row.active_cycle_id = cycle_id
    task_row.active_scheduled_for = _NOW
    cycle_repository = ScheduledTaskCycleRepository(ToolkitStateRepository())
    cycle = await cycle_repository.create_admitted(
        session,
        ScheduledTaskCycleSnapshot(
            cycle_id=cycle_id,
            task_id=task.id,
            workspace_id=subject.workspace_id,
            agent_id=subject.agent_id,
            session_id=subject.session_id,
            binding_id=None,
            title=title,
            objective=f"Run {title}.",
            schedule_type=ScheduledTaskScheduleType.ONCE,
            scheduled_at=_NOW,
            cron_expression=None,
            timezone=None,
            scheduled_for=_NOW,
        ),
    )
    trigger = await MailboxRepository().create_idempotent(
        session,
        MailboxItemCreate(
            session_id=subject.session_id,
            kind=MailboxItemKind.SCHEDULED_TASK_TRIGGER,
            scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            sender_user_id=None,
            order_group=None,
            order_sequence=0,
            content=f"Run {title}.",
            idempotency_key=f"scheduled-task-trigger:{cycle_id}",
            metadata={"cycle_id": cycle_id, "title": title},
            action=None,
            attachments=[],
            file_parts=[],
            payload=None,
        ),
        idempotency_key=f"scheduled-task-trigger:{cycle_id}",
    )
    run_id: str | None = None
    if started:
        run = RDBAgentRun(
            session_id=subject.session_id,
            scheduled_task_cycle_id=cycle_id,
            run_index=1,
            parent_agent_run_id=None,
            status=AgentRunStatus.RUNNING,
        )
        session.add(run)
        await session.flush()
        cycle = await cycle_repository.start(
            session,
            record=cycle,
            run_id=run.id,
            started_at=_NOW,
        )
        assert await MailboxRepository().delete_by_session_and_id(
            session,
            subject.session_id,
            trigger.id,
        )
        run_id = run.id
    await session.flush()
    return _TaskCycle(
        task_id=task.id,
        cycle=cycle,
        trigger_id=trigger.id,
        run_id=run_id,
    )


class TestScheduledTaskLifecycleRepository:
    """Lifecycle deletion and preservation integration tests."""

    async def test_binding_termination_fences_task_retarget_before_delete(
        self,
    ) -> None:
        """A Task moved to another Binding is not deleted by a stale terminator."""
        candidate = _rdb_task(binding_id="b" * 32)
        locked = _rdb_task(binding_id="n" * 32)
        session = _BindingFenceSession(locked)

        cleanup = await ScheduledTaskLifecycleRepository()._terminate_tasks(
            cast(AsyncSession, session),
            tasks=[candidate],
            expected_binding_id="b" * 32,
        )

        assert cleanup.deleted_task_count == 0
        assert cleanup.cleanup_plans == ()
        assert session.deleted == []
        assert session.flushed is True

    async def test_terminate_session_tree_deletes_prestart_and_preserves_started(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Archive removes Task authority but preserves a started cycle and Run."""
        subject = await _create_subject(
            rdb_session,
            handle="scheduled-lifecycle-archive",
        )
        admitted = await _create_task_cycle(
            rdb_session,
            subject=subject,
            title="Admitted task",
            started=False,
        )
        started = await _create_task_cycle(
            rdb_session,
            subject=subject,
            title="Started task",
            started=True,
        )

        cleanup = await ScheduledTaskLifecycleRepository().terminate_session_tree(
            rdb_session,
            session_ids=[subject.session_id],
        )

        assert cleanup.deleted_task_count == 2
        assert cleanup.deleted_admitted_cycle_count == 1
        assert cleanup.deleted_trigger_count == 1
        assert cleanup.preserved_started_cycle_count == 1
        assert cleanup.cleanup_plans == ()
        assert (
            await rdb_session.scalar(
                sa.select(sa.func.count()).select_from(RDBScheduledTask)
            )
            == 0
        )
        assert await rdb_session.get(RDBMailboxItem, admitted.trigger_id) is None
        assert await rdb_session.get(RDBMailboxItem, started.trigger_id) is None
        cycle_repository = ScheduledTaskCycleRepository(ToolkitStateRepository())
        assert (
            await cycle_repository.get(
                rdb_session,
                agent_id=subject.agent_id,
                session_id=subject.session_id,
                cycle_id=admitted.cycle.state.cycle_id,
            )
            is None
        )
        preserved = await cycle_repository.get_started(
            rdb_session,
            agent_id=subject.agent_id,
            session_id=subject.session_id,
            cycle_id=started.cycle.state.cycle_id,
        )
        assert preserved is not None
        assert preserved.state.current_run_id == started.run_id
        assert started.run_id is not None
        assert await rdb_session.get(RDBAgentRun, started.run_id) is not None

    async def test_archive_allows_only_exact_started_scheduled_runs(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Ordinary or mismatched active Runs retain the archive block."""
        subject = await _create_subject(
            rdb_session,
            handle="scheduled-lifecycle-eligibility",
        )
        started = await _create_task_cycle(
            rdb_session,
            subject=subject,
            title="Started task",
            started=True,
        )
        repository = ScheduledTaskLifecycleRepository()

        assert await repository.archive_allows_active_runs(
            rdb_session,
            session_ids=[subject.session_id],
            running_session_ids=[subject.session_id],
        )

        ordinary = RDBAgentRun(
            session_id=subject.session_id,
            scheduled_task_cycle_id=None,
            run_index=2,
            parent_agent_run_id=None,
            status=AgentRunStatus.PENDING,
        )
        rdb_session.add(ordinary)
        await rdb_session.flush()

        assert not await repository.archive_allows_active_runs(
            rdb_session,
            session_ids=[subject.session_id],
            running_session_ids=[subject.session_id],
        )
        assert started.run_id is not None

    async def test_archive_allows_prestart_trigger_for_transactional_cleanup(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A valid pre-start trigger may be removed by the archive transaction."""
        subject = await _create_subject(
            rdb_session,
            handle="scheduled-lifecycle-prestart-eligibility",
        )
        await _create_task_cycle(
            rdb_session,
            subject=subject,
            title="Admitted task",
            started=False,
        )

        assert await ScheduledTaskLifecycleRepository().archive_allows_active_runs(
            rdb_session,
            session_ids=[subject.session_id],
            running_session_ids=[subject.session_id],
        )

    async def test_terminate_session_tree_deletes_orphan_trigger(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Archive removes a Scheduled trigger after its Task and cycle disappeared."""
        subject = await _create_subject(
            rdb_session,
            handle="scheduled-lifecycle-orphan-trigger",
        )
        admitted = await _create_task_cycle(
            rdb_session,
            subject=subject,
            title="Orphaned admitted task",
            started=False,
        )
        task = await rdb_session.get(RDBScheduledTask, admitted.task_id)
        assert task is not None
        await rdb_session.delete(task)
        assert await ScheduledTaskCycleRepository(
            ToolkitStateRepository()
        ).delete_if_admitted(
            rdb_session,
            agent_id=subject.agent_id,
            session_id=subject.session_id,
            cycle_id=admitted.cycle.state.cycle_id,
        )
        await rdb_session.flush()
        repository = ScheduledTaskLifecycleRepository()

        before = await repository.verify_session_tree(
            rdb_session,
            session_ids=[subject.session_id],
        )
        assert before.task_count == 0
        assert before.trigger_count == 1
        assert before.admitted_cycle_count == 0

        cleanup = await repository.terminate_session_tree(
            rdb_session,
            session_ids=[subject.session_id],
        )

        assert cleanup.deleted_task_count == 0
        assert cleanup.deleted_admitted_cycle_count == 0
        assert cleanup.deleted_trigger_count == 1
        assert await rdb_session.get(RDBMailboxItem, admitted.trigger_id) is None

    async def test_terminate_binding_deletes_orphan_admitted_cycle_and_trigger(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Binding termination removes cycle-owned work without a Task row."""
        subject = await _create_subject(
            rdb_session,
            handle="scheduled-lifecycle-binding-orphan",
        )
        binding_id = "b" * 32
        cycle_id = uuid7().hex
        cycle = await ScheduledTaskCycleRepository(
            ToolkitStateRepository()
        ).create_admitted(
            rdb_session,
            ScheduledTaskCycleSnapshot(
                cycle_id=cycle_id,
                task_id="t" * 32,
                workspace_id=subject.workspace_id,
                agent_id=subject.agent_id,
                session_id=subject.session_id,
                binding_id=binding_id,
                title="Binding orphan",
                objective="Run the binding orphan.",
                schedule_type=ScheduledTaskScheduleType.ONCE,
                scheduled_at=_NOW,
                cron_expression=None,
                timezone=None,
                scheduled_for=_NOW,
            ),
        )
        trigger = await MailboxRepository().create_idempotent(
            rdb_session,
            MailboxItemCreate(
                session_id=subject.session_id,
                kind=MailboxItemKind.SCHEDULED_TASK_TRIGGER,
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                sender_user_id=None,
                order_group=None,
                order_sequence=0,
                content="Run the binding orphan.",
                idempotency_key=f"scheduled-task-trigger:{cycle_id}",
                metadata={"cycle_id": cycle_id, "title": "Binding orphan"},
                action=None,
                attachments=[],
                file_parts=[],
                payload=None,
            ),
            idempotency_key=f"scheduled-task-trigger:{cycle_id}",
        )

        cleanup = await ScheduledTaskLifecycleRepository().terminate_binding(
            rdb_session,
            binding_id=binding_id,
        )

        assert cleanup.deleted_task_count == 0
        assert cleanup.deleted_admitted_cycle_count == 1
        assert cleanup.deleted_trigger_count == 1
        assert await rdb_session.get(RDBMailboxItem, trigger.id) is None
        assert (
            await ScheduledTaskCycleRepository(ToolkitStateRepository()).get(
                rdb_session,
                agent_id=subject.agent_id,
                session_id=subject.session_id,
                cycle_id=cycle.state.cycle_id,
            )
            is None
        )

    async def test_purge_waits_for_started_cycle_and_verifies_absence(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Permanent purge remains fenced until preserved cycle state is gone."""
        subject = await _create_subject(
            rdb_session,
            handle="scheduled-lifecycle-purge",
        )
        started = await _create_task_cycle(
            rdb_session,
            subject=subject,
            title="Started task",
            started=True,
        )
        repository = ScheduledTaskLifecycleRepository()
        await repository.terminate_session_tree(
            rdb_session,
            session_ids=[subject.session_id],
        )

        with pytest.raises(RuntimeError, match="started cycles remain active"):
            await repository.require_purge_ready(
                rdb_session,
                session_ids=[subject.session_id],
            )

        cycle_repository = ScheduledTaskCycleRepository(ToolkitStateRepository())
        preserved = await cycle_repository.get_started(
            rdb_session,
            agent_id=subject.agent_id,
            session_id=subject.session_id,
            cycle_id=started.cycle.state.cycle_id,
        )
        assert preserved is not None
        assert await cycle_repository.delete_started(
            rdb_session,
            record=preserved,
        )

        verification = await repository.require_purge_ready(
            rdb_session,
            session_ids=[subject.session_id],
        )
        assert verification.task_count == 0
        assert verification.trigger_count == 0
        assert verification.admitted_cycle_count == 0
        assert verification.started_cycle_count == 0
