"""Repository-owned Scheduled Task progress operation tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
    ExternalChannelWorkProjectionStatus,
    ExternalChannelWorkTaskStatus,
    ScheduledTaskScheduleType,
)
from azents.core.external_channel_progress import ExternalChannelWorkTask
from azents.core.external_channel_provider_effect import (
    ProviderEffectPlan,
    ProviderOperationKey,
    ProviderTarget,
)
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import (
    ScheduledTaskCycleRecord,
    ScheduledTaskCycleState,
    ScheduledTrackerProjectionPart,
)
from azents.repos.scheduled_task_cycle.progress import (
    ScheduledTaskProgressRepository,
)
from azents.repos.scheduled_task_cycle.progress_data import (
    ScheduledTaskTrackerEffect,
)
from azents.testing.types import require_instance

_NOW = datetime.datetime(2026, 9, 8, 12, 0, tzinfo=datetime.UTC)
_AGENT_ID = "a" * 32
_SESSION_ID = "s" * 32
_CYCLE_ID = "c" * 32
_BINDING_ID = "b" * 32
_RUN_ID = "r" * 32


class _TrackedSession(AsyncSession):
    """Expose the repository context lifetime through in_transaction."""

    def __init__(self) -> None:
        super().__init__()
        self.active = True

    def in_transaction(self) -> bool:
        """Return whether the repository context still owns this session."""
        return self.active


class _TransactionTracker:
    """Create sessions whose transaction lifetime is directly observable."""

    def __init__(self) -> None:
        self.sessions: list[AsyncSession] = []

    @asynccontextmanager
    async def session_manager(self) -> AsyncIterator[AsyncSession]:
        session = _TrackedSession()
        self.sessions.append(session)
        try:
            yield session
        finally:
            session.active = False
            await session.close()

    def assert_inactive(self) -> None:
        """Assert every repository transaction context has completed."""
        assert self.sessions
        assert all(not session.in_transaction() for session in self.sessions)


def _cycle(
    *,
    desired_revision: int = 0,
    projection_parts: list[ScheduledTrackerProjectionPart] | None = None,
    version: int = 2,
) -> ScheduledTaskCycleRecord:
    return ScheduledTaskCycleRecord(
        state=ScheduledTaskCycleState(
            cycle_id=_CYCLE_ID,
            task_id="t" * 32,
            phase="started",
            workspace_id="w" * 32,
            agent_id=_AGENT_ID,
            session_id=_SESSION_ID,
            binding_id=_BINDING_ID,
            title="Daily report",
            objective="Prepare the report.",
            schedule_type=ScheduledTaskScheduleType.ONCE,
            scheduled_at=_NOW,
            cron_expression=None,
            timezone=None,
            scheduled_for=_NOW,
            current_run_id=_RUN_ID,
            started_at=_NOW,
            progress_title=None,
            tracker_desired_revision=desired_revision,
            tracker_current_projection_parts=projection_parts or [],
        ),
        version=version,
        toolkit_state_id="k" * 32,
    )


def _plan(
    operation: ExternalChannelDeliveryOperation,
    *,
    seed: str,
) -> ProviderEffectPlan:
    return ProviderEffectPlan(
        target=ProviderTarget(
            operation=operation,
            binding_id=_BINDING_ID,
            resource_id="q" * 32,
            connection_id="n" * 32,
            provider=ExternalChannelProvider.SLACK,
            app_mode=ExternalChannelAppMode.SINGLE,
            encrypted_credentials="encrypted",
            provider_tenant_id="tenant",
            capabilities=None,
            provider_configuration=None,
            workspace_handle="workspace",
            agent_id=_AGENT_ID,
            agent_session_id=_SESSION_ID,
            agent_name="Agent",
            agent_avatar=None,
            request_payload={},
        ),
        operation_key=ProviderOperationKey.from_seed(seed),
    )


def _repository(
    tracker: _TransactionTracker,
) -> tuple[
    ScheduledTaskProgressRepository,
    AsyncMock,
    AsyncMock,
    AsyncMock,
]:
    run_repository = AsyncMock(spec=AgentRunRepository)
    cycle_repository = AsyncMock(spec=ScheduledTaskCycleRepository)
    provider_repository = AsyncMock(spec=ExternalChannelWorkRepository)
    repository = ScheduledTaskProgressRepository(
        session_manager=tracker.session_manager,
        run_repository=require_instance(run_repository, AgentRunRepository),
        cycle_repository=require_instance(
            cycle_repository,
            ScheduledTaskCycleRepository,
        ),
        provider_repository=require_instance(
            provider_repository,
            ExternalChannelWorkRepository,
        ),
    )
    return repository, run_repository, cycle_repository, provider_repository


def _scheduled_run() -> SimpleNamespace:
    return SimpleNamespace(
        session_id=_SESSION_ID,
        scheduled_task_cycle_id=_CYCLE_ID,
    )


def _task() -> ExternalChannelWorkTask:
    return ExternalChannelWorkTask(
        id="collect",
        title="Collect data",
        status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
        details=None,
        output=None,
        sources=[],
    )


@pytest.mark.asyncio
async def test_prepare_progress_commits_plans_and_stable_operation_seeds() -> None:
    tracker = _TransactionTracker()
    repository, run_repository, cycle_repository, provider_repository = _repository(
        tracker
    )
    initial = _cycle()
    updated = _cycle(desired_revision=1, version=3)
    claimed = _cycle(
        desired_revision=1,
        projection_parts=[
            ScheduledTrackerProjectionPart(
                part_ordinal=0,
                desired_revision=1,
                status=ExternalChannelWorkProjectionStatus.UNKNOWN,
                provider_message_key=None,
            )
        ],
        version=4,
    )
    run_repository.get_by_id.return_value = _scheduled_run()
    cycle_repository.lock.return_value = initial
    cycle_repository.update_progress.return_value = updated
    cycle_repository.claim_tracker_projection.return_value = claimed

    async def prepare_tracker(
        _session: AsyncSession,
        **kwargs: object,
    ) -> ProviderEffectPlan:
        seed = kwargs["operation_seed"]
        assert isinstance(seed, str)
        return _plan(ExternalChannelDeliveryOperation.PROGRESS_CREATE, seed=seed)

    async def prepare_reply(
        _session: AsyncSession,
        **kwargs: object,
    ) -> tuple[ProviderEffectPlan, ...]:
        seed = kwargs["operation_seed"]
        assert isinstance(seed, str)
        return (_plan(ExternalChannelDeliveryOperation.REPLY, seed=seed),)

    provider_repository.prepare_binding_effect.side_effect = prepare_tracker
    provider_repository.prepare_binding_reply_effects.side_effect = prepare_reply

    first = await repository.prepare_progress(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        run_id=_RUN_ID,
        binding_id=_BINDING_ID,
        mode=ExternalChannelActionMode.CONTINUE,
        message="Working on it.",
        title="Preparing the report…",
        tasks=(_task(),),
        files=(),
    )
    second = await repository.prepare_progress(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        run_id=_RUN_ID,
        binding_id=_BINDING_ID,
        mode=ExternalChannelActionMode.CONTINUE,
        message="Working on it.",
        title="Preparing the report…",
        tasks=(_task(),),
        files=(),
    )

    tracker.assert_inactive()
    assert first.status == second.status == "prepared"
    assert first.state_revision == second.state_revision == 4
    assert first.tracker is not None
    assert second.tracker is not None
    assert first.tracker.plan.operation_key == second.tracker.plan.operation_key
    assert first.reply_plans[0].operation_key == second.reply_plans[0].operation_key
    tracker_calls = provider_repository.prepare_binding_effect.await_args_list
    assert [call.kwargs["operation_seed"] for call in tracker_calls] == [
        f"scheduled-tracker:{_CYCLE_ID}:1:0",
        f"scheduled-tracker:{_CYCLE_ID}:1:0",
    ]
    reply_calls = provider_repository.prepare_binding_reply_effects.await_args_list
    assert [call.kwargs["operation_seed"] for call in reply_calls] == [
        f"scheduled-progress:{_CYCLE_ID}",
        f"scheduled-progress:{_CYCLE_ID}",
    ]


@pytest.mark.asyncio
async def test_initial_tracker_preserves_scheduled_presentation_and_seed() -> None:
    tracker = _TransactionTracker()
    repository, _, cycle_repository, provider_repository = _repository(tracker)
    cycle_repository.get_started.return_value = _cycle()
    cycle_repository.claim_tracker_projection.return_value = _cycle(version=3)
    provider_repository.prepare_binding_effect.return_value = _plan(
        ExternalChannelDeliveryOperation.PROGRESS_CREATE,
        seed=f"scheduled-tracker:{_CYCLE_ID}:0:0",
    )

    effect = await repository.prepare_initial_tracker(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        cycle_id=_CYCLE_ID,
    )

    tracker.assert_inactive()
    assert effect is not None
    _, kwargs = provider_repository.prepare_binding_effect.await_args
    assert kwargs["operation_seed"] == f"scheduled-tracker:{_CYCLE_ID}:0:0"
    assert kwargs["slack_payload"]["text"] == (
        "Agent is running a scheduled task…\nDaily report"
    )
    assert kwargs["discord_payload"]["embeds"][0]["description"] == (
        "◉ Agent is running a scheduled task…\nDaily report"
    )
    assert kwargs["discord_payload"]["tracker_kind"] == "scheduled_task"
    assert "Prepare the report." not in str(kwargs)


@pytest.mark.asyncio
async def test_not_scheduled_precedes_scheduled_only_validation() -> None:
    tracker = _TransactionTracker()
    repository, run_repository, cycle_repository, _ = _repository(tracker)
    run_repository.get_by_id.return_value = None

    preparation = await repository.prepare_progress(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        run_id=_RUN_ID,
        binding_id=_BINDING_ID,
        mode=ExternalChannelActionMode.FINISH,
        message="Finished.",
        title=None,
        tasks=None,
        files=(),
    )

    assert preparation.status == "not_scheduled"
    cycle_repository.lock.assert_not_awaited()
    tracker.assert_inactive()


@pytest.mark.asyncio
async def test_admission_rejects_superseded_and_inactive_cycles() -> None:
    tracker = _TransactionTracker()
    repository, run_repository, cycle_repository, _ = _repository(tracker)
    run_repository.get_by_id.return_value = _scheduled_run()
    cycle_repository.lock.side_effect = [_cycle(version=5), None]

    superseded = await repository.admit_progress_effects(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        run_id=_RUN_ID,
        state_revision=4,
        tracker_expected_desired_revision=1,
    )
    inactive = await repository.admit_progress_effects(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        run_id=_RUN_ID,
        state_revision=4,
        tracker_expected_desired_revision=1,
    )

    assert superseded.status == "superseded"
    assert inactive.status == "inactive"
    tracker.assert_inactive()


@pytest.mark.asyncio
async def test_settlement_uses_fresh_completed_repository_transaction() -> None:
    tracker = _TransactionTracker()
    repository, _, cycle_repository, _ = _repository(tracker)
    effect_plan = _plan(
        ExternalChannelDeliveryOperation.PROGRESS_CREATE,
        seed=f"scheduled-tracker:{_CYCLE_ID}:1:0",
    )
    cycle_repository.settle_tracker_projection.return_value = False

    settled = await repository.settle_tracker(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        cycle_id=_CYCLE_ID,
        effect=ScheduledTaskTrackerEffect(
            plan=effect_plan,
            expected_desired_revision=1,
            part_ordinal=0,
        ),
        status=ExternalChannelWorkProjectionStatus.PRESENT,
        provider_message_key="slack:tenant:channel:tracker",
    )

    assert not settled
    tracker.assert_inactive()
    cycle_repository.settle_tracker_projection.assert_awaited_once()
