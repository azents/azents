"""Scheduled-owned External Channel orchestration tests."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import NamedTuple
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
    ExternalChannelWorkProjectionStatus,
    ExternalChannelWorkTaskStatus,
    ScheduledTaskScheduleType,
)
from azents.core.external_channel_file import (
    ExternalChannelOutboundFileManifest,
    ExternalChannelOutboundFileSource,
)
from azents.core.external_channel_progress import ExternalChannelWorkTask
from azents.core.external_channel_provider_effect import (
    ProviderEffectPlan,
    ProviderMutationOutcome,
    ProviderOperationKey,
    ProviderTarget,
)
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.scheduled_task.data import ScheduledTask
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
    ScheduledTaskProgressAdmission,
    ScheduledTaskProgressPreparation,
    ScheduledTaskTrackerEffect,
)
from azents.runtime.transfer.runtime_to_provider import (
    RuntimeToProviderDeliveryExecutor,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.services.external_channel.channel_action import ExternalChannelActionService
from azents.services.file_storage import FileStorage
from azents.services.scheduled_task.channel import ScheduledTaskChannelService
from azents.services.scheduled_task.terminal import (
    ScheduledTaskTerminalEffectSnapshot,
)
from azents.services.session_resource_authority import SessionResourceAuthority
from azents.testing.types import require_instance

_NOW = datetime.datetime(2026, 8, 16, 12, 0, tzinfo=datetime.UTC)
_AGENT_ID = "a" * 32
_SESSION_ID = "s" * 32
_CYCLE_ID = "c" * 32
_BINDING_ID = "b" * 32
_RUN_ID = "r" * 32


@asynccontextmanager
async def _session_manager() -> AsyncIterator[AsyncSession]:
    yield require_instance(MagicMock(spec=AsyncSession), AsyncSession)


class _TrackedSession(AsyncSession):
    """Expose one repository context lifetime through in_transaction."""

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


def _task() -> ScheduledTask:
    return ScheduledTask(
        id="t" * 32,
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
        next_eligible_at=_NOW,
        active_cycle_id=None,
        active_scheduled_for=None,
        pending_scheduled_for=None,
        lease_owner=None,
        lease_until=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _plan(
    operation: ExternalChannelDeliveryOperation,
    *,
    payload: dict[str, object] | None = None,
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
            request_payload=payload or {},
        ),
        operation_key=ProviderOperationKey.from_seed(
            f"{operation.value}:{len(payload or {})}"
        ),
    )


class _ServiceFixture(NamedTuple):
    """Scheduled Channel service and its mock collaborators."""

    service: ScheduledTaskChannelService
    progress_repository: AsyncMock
    provider_repository: AsyncMock
    action_service: AsyncMock


def _service() -> _ServiceFixture:
    progress_repository = AsyncMock(spec=ScheduledTaskProgressRepository)
    provider_repository = AsyncMock(spec=ExternalChannelWorkRepository)
    action_service = AsyncMock(spec=ExternalChannelActionService)
    config = require_instance(
        MagicMock(
            spec=Config,
            auth=SimpleNamespace(jwt=SimpleNamespace(secret_key="test-secret")),
        ),
        Config,
    )
    service = ScheduledTaskChannelService(
        session_manager=_session_manager,
        progress_repository=require_instance(
            progress_repository,
            ScheduledTaskProgressRepository,
        ),
        provider_repository=require_instance(
            provider_repository,
            ExternalChannelWorkRepository,
        ),
        action_service=require_instance(action_service, ExternalChannelActionService),
        config=config,
    )
    return _ServiceFixture(
        service,
        progress_repository,
        provider_repository,
        action_service,
    )


def _tracker_effect(
    plan: ProviderEffectPlan,
    *,
    desired_revision: int = 1,
) -> ScheduledTaskTrackerEffect:
    return ScheduledTaskTrackerEffect(
        plan=plan,
        expected_desired_revision=desired_revision,
        part_ordinal=0,
    )


def _prepared(
    *,
    state_revision: int,
    reply_plans: tuple[ProviderEffectPlan, ...] = (),
    tracker: ScheduledTaskTrackerEffect | None = None,
) -> ScheduledTaskProgressPreparation:
    return ScheduledTaskProgressPreparation(
        status="prepared",
        cycle_id=_CYCLE_ID,
        state_revision=state_revision,
        reply_plans=reply_plans,
        tracker=tracker,
    )


@pytest.mark.asyncio
async def test_initial_tracker_executes_and_settles_prepared_effect() -> None:
    service, progress_repository, _, action_service = _service()
    plan = _plan(ExternalChannelDeliveryOperation.PROGRESS_CREATE)
    tracker = _tracker_effect(plan, desired_revision=0)
    progress_repository.prepare_initial_tracker.return_value = tracker
    action_service.execute_binding_effect.return_value = ProviderMutationOutcome(
        status="delivered",
        provider_message_key="slack:tenant:channel:tracker",
        error_kind=None,
        error_summary=None,
    )

    outcome = await service.create_initial_tracker(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        cycle_id=_CYCLE_ID,
    )

    assert outcome is not None
    progress_repository.settle_tracker.assert_awaited_once_with(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        cycle_id=_CYCLE_ID,
        effect=tracker,
        status=ExternalChannelWorkProjectionStatus.PRESENT,
        provider_message_key="slack:tenant:channel:tracker",
    )


@pytest.mark.asyncio
async def test_registration_uses_exact_binding_and_returns_immediate_outcome() -> None:
    service, _, provider_repository, action_service = _service()
    plan = _plan(ExternalChannelDeliveryOperation.CONTROL_MESSAGE)
    provider_repository.prepare_binding_effect.return_value = plan
    action_service.execute_binding_effect.return_value = ProviderMutationOutcome(
        status="failed",
        provider_message_key=None,
        error_kind="provider_rejected",
        error_summary="The provider rejected the registration.",
    )

    outcome = await service.execute_registration(_task())

    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.reason == "provider_rejected"
    _, kwargs = provider_repository.prepare_binding_effect.await_args
    assert kwargs["binding_id"] == _BINDING_ID
    assert kwargs["operation"] is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
    assert kwargs["slack_payload"]["control_kind"] == ("scheduled_task_registration")
    assert kwargs["discord_payload"]["text"] == ""
    assert kwargs["discord_payload"]["task_id"] == "t" * 32
    assert isinstance(kwargs["discord_payload"]["delete_locator"], str)
    assert "components" not in kwargs["discord_payload"]
    assert "Prepare the report." not in str(kwargs["slack_payload"])


@pytest.mark.asyncio
async def test_deletion_uses_exact_binding_and_returns_immediate_outcome() -> None:
    service, _, provider_repository, action_service = _service()
    plan = _plan(ExternalChannelDeliveryOperation.CONTROL_MESSAGE)
    provider_repository.prepare_binding_effect.return_value = plan
    action_service.execute_binding_effect.return_value = ProviderMutationOutcome(
        status="delivered",
        provider_message_key="slack:tenant:channel:deletion",
        error_kind=None,
        error_summary=None,
    )

    outcome = await service.execute_deletion(_task())

    assert outcome is not None
    assert outcome.status == "delivered"
    _, kwargs = provider_repository.prepare_binding_effect.await_args
    assert kwargs["binding_id"] == _BINDING_ID
    assert kwargs["operation"] is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
    assert kwargs["operation_seed"] == f"scheduled-deletion:{'t' * 32}"
    assert kwargs["slack_payload"]["control_kind"] == "scheduled_task_deletion"
    assert kwargs["discord_payload"]["control_kind"] == "scheduled_task_deletion"
    assert kwargs["discord_payload"]["text"] == ""
    assert "Scheduled Task deleted: Daily report" in str(kwargs["slack_payload"])
    assert "Prepare the report." not in str(kwargs["discord_payload"])


@pytest.mark.asyncio
async def test_session_only_deletion_has_no_provider_effect() -> None:
    service, _, provider_repository, action_service = _service()

    outcome = await service.execute_deletion(
        dataclasses.replace(_task(), binding_id=None)
    )

    assert outcome is None
    provider_repository.prepare_binding_effect.assert_not_awaited()
    action_service.execute_binding_effect.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduled_continue_updates_and_settles_tracker() -> None:
    service, progress_repository, _, action_service = _service()
    reply_plan = _plan(ExternalChannelDeliveryOperation.REPLY)
    tracker_plan = _plan(ExternalChannelDeliveryOperation.PROGRESS_CREATE)
    tracker = _tracker_effect(tracker_plan)
    progress_repository.prepare_progress.return_value = _prepared(
        state_revision=4,
        reply_plans=(reply_plan,),
        tracker=tracker,
    )
    progress_repository.admit_progress_effects.return_value = (
        ScheduledTaskProgressAdmission(
            status="admitted",
            tracker_current=True,
        )
    )
    progress_repository.settle_tracker.return_value = True
    action_service.execute_binding_effect.side_effect = [
        ProviderMutationOutcome(
            status="failed",
            provider_message_key=None,
            error_kind="reply_failed",
            error_summary="The interim reply failed.",
        ),
        ProviderMutationOutcome(
            status="delivered",
            provider_message_key="slack:tenant:channel:tracker",
            error_kind=None,
            error_summary=None,
        ),
    ]
    task = ExternalChannelWorkTask(
        id="collect",
        title="Collect data",
        status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
        details=None,
        output=None,
        sources=[],
    )

    execution = await service.execute_progress(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        run_id=_RUN_ID,
        binding_id=_BINDING_ID,
        mode=ExternalChannelActionMode.CONTINUE,
        message="Working on it.",
        title="Preparing the report…",
        tasks=[task],
        files=(),
        file_storage=None,
        authority=None,
        provider_delivery_service=None,
        resolve_runtime_target=None,
    )

    assert execution.result is not None
    assert execution.result.state_revision == 4
    assert [outcome.operation for outcome in execution.result.outcomes] == [
        ExternalChannelDeliveryOperation.REPLY,
        ExternalChannelDeliveryOperation.PROGRESS_CREATE,
    ]
    progress_repository.settle_tracker.assert_awaited_once_with(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        cycle_id=_CYCLE_ID,
        effect=tracker,
        status=ExternalChannelWorkProjectionStatus.PRESENT,
        provider_message_key="slack:tenant:channel:tracker",
    )
    assert action_service.execute_binding_effect.await_args_list == [
        call(
            reply_plan,
            file_storage=None,
            agent_id=_AGENT_ID,
            session_id=_SESSION_ID,
            authority=None,
            provider_delivery_service=None,
            resolve_runtime_target=None,
        ),
        call(tracker_plan),
    ]


@pytest.mark.asyncio
async def test_external_effects_observe_zero_active_database_transactions() -> None:
    transaction_tracker = _TransactionTracker()
    run_repository = AsyncMock(spec=AgentRunRepository)
    cycle_repository = AsyncMock(spec=ScheduledTaskCycleRepository)
    provider_repository = AsyncMock(spec=ExternalChannelWorkRepository)
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
    run_repository.get_by_id.return_value = SimpleNamespace(
        session_id=_SESSION_ID,
        scheduled_task_cycle_id=_CYCLE_ID,
    )
    cycle_repository.lock.side_effect = [initial, claimed]
    cycle_repository.update_progress.return_value = updated
    cycle_repository.claim_tracker_projection.return_value = claimed
    cycle_repository.settle_tracker_projection.return_value = True
    reply_plan = _plan(ExternalChannelDeliveryOperation.REPLY)
    tracker_plan = _plan(ExternalChannelDeliveryOperation.PROGRESS_CREATE)
    provider_repository.prepare_binding_reply_effects.return_value = (reply_plan,)
    provider_repository.prepare_binding_effect.return_value = tracker_plan
    progress_repository = ScheduledTaskProgressRepository(
        session_manager=transaction_tracker.session_manager,
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
    action_service = AsyncMock(spec=ExternalChannelActionService)

    async def execute_effect(
        plan: ProviderEffectPlan,
        **_: object,
    ) -> ProviderMutationOutcome:
        transaction_tracker.assert_inactive()
        return ProviderMutationOutcome(
            status="delivered",
            provider_message_key=(
                "slack:tenant:channel:tracker"
                if plan.target.operation
                is ExternalChannelDeliveryOperation.PROGRESS_CREATE
                else "slack:tenant:channel:reply"
            ),
            error_kind=None,
            error_summary=None,
        )

    action_service.execute_binding_effect.side_effect = execute_effect
    config = require_instance(
        MagicMock(
            spec=Config,
            auth=SimpleNamespace(jwt=SimpleNamespace(secret_key="test-secret")),
        ),
        Config,
    )
    service = ScheduledTaskChannelService(
        session_manager=transaction_tracker.session_manager,
        progress_repository=progress_repository,
        provider_repository=require_instance(
            provider_repository,
            ExternalChannelWorkRepository,
        ),
        action_service=require_instance(
            action_service,
            ExternalChannelActionService,
        ),
        config=config,
    )

    execution = await service.execute_progress(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        run_id=_RUN_ID,
        binding_id=_BINDING_ID,
        mode=ExternalChannelActionMode.CONTINUE,
        message="Working on it.",
        title="Preparing the report…",
        tasks=[
            ExternalChannelWorkTask(
                id="collect",
                title="Collect data",
                status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
                details=None,
                output=None,
                sources=[],
            )
        ],
        files=(),
        file_storage=None,
        authority=None,
        provider_delivery_service=None,
        resolve_runtime_target=None,
    )

    assert execution.result is not None
    assert len(transaction_tracker.sessions) == 3
    transaction_tracker.assert_inactive()
    assert action_service.execute_binding_effect.await_count == 2


@pytest.mark.asyncio
async def test_terminalization_winning_after_progress_commit_suppresses_effects() -> (
    None
):
    """A deleted cycle cannot fall through or publish its prepared reply."""
    service, progress_repository, _, action_service = _service()
    reply_plan = _plan(ExternalChannelDeliveryOperation.REPLY)
    progress_repository.prepare_progress.return_value = _prepared(
        state_revision=2,
        reply_plans=(reply_plan,),
    )
    progress_repository.admit_progress_effects.return_value = (
        ScheduledTaskProgressAdmission(
            status="inactive",
            tracker_current=False,
        )
    )

    execution = await service.execute_progress(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        run_id=_RUN_ID,
        binding_id=_BINDING_ID,
        mode=ExternalChannelActionMode.CONTINUE,
        message="Working on it.",
        title=None,
        tasks=None,
        files=(),
        file_storage=None,
        authority=None,
        provider_delivery_service=None,
        resolve_runtime_target=None,
    )

    assert execution.result is not None
    assert len(execution.result.outcomes) == 1
    assert execution.result.outcomes[0].status == "not_attempted"
    assert execution.result.outcomes[0].reason == "scheduled_cycle_inactive"
    action_service.execute_binding_effect.assert_not_awaited()


@pytest.mark.asyncio
async def test_newer_progress_revision_suppresses_prepared_reply_and_tracker() -> None:
    """A newer canonical progress revision fences every older provider effect."""
    service, progress_repository, _, action_service = _service()
    reply_plan = _plan(ExternalChannelDeliveryOperation.REPLY)
    tracker_plan = _plan(ExternalChannelDeliveryOperation.PROGRESS_CREATE)
    tracker = _tracker_effect(tracker_plan)
    progress_repository.prepare_progress.return_value = _prepared(
        state_revision=4,
        reply_plans=(reply_plan,),
        tracker=tracker,
    )
    admission_started = asyncio.Event()
    newer_revision_committed = asyncio.Event()

    async def admit_after_newer_revision(**_: object) -> ScheduledTaskProgressAdmission:
        admission_started.set()
        await newer_revision_committed.wait()
        return ScheduledTaskProgressAdmission(
            status="superseded",
            tracker_current=False,
        )

    progress_repository.admit_progress_effects.side_effect = admit_after_newer_revision
    task = ExternalChannelWorkTask(
        id="collect",
        title="Collect data",
        status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
        details=None,
        output=None,
        sources=[],
    )

    execution_task = asyncio.create_task(
        service.execute_progress(
            agent_id=_AGENT_ID,
            session_id=_SESSION_ID,
            run_id=_RUN_ID,
            binding_id=_BINDING_ID,
            mode=ExternalChannelActionMode.CONTINUE,
            message="Working on it.",
            title="Preparing the report…",
            tasks=[task],
            files=(),
            file_storage=None,
            authority=None,
            provider_delivery_service=None,
            resolve_runtime_target=None,
        )
    )
    await admission_started.wait()
    newer_revision_committed.set()
    execution = await execution_task

    assert execution.result is not None
    assert [outcome.reason for outcome in execution.result.outcomes] == [
        "scheduled_progress_superseded",
        "scheduled_progress_superseded",
    ]
    assert all(
        outcome.status == "not_attempted" for outcome in execution.result.outcomes
    )
    action_service.execute_binding_effect.assert_not_awaited()
    progress_repository.settle_tracker.assert_not_awaited()


@pytest.mark.asyncio
async def test_newer_progress_revision_suppresses_message_only_reply() -> None:
    """Message-only publication is fenced by the cycle version it observed."""
    service, progress_repository, _, action_service = _service()
    reply_plan = _plan(ExternalChannelDeliveryOperation.REPLY)
    progress_repository.prepare_progress.return_value = _prepared(
        state_revision=2,
        reply_plans=(reply_plan,),
    )
    progress_repository.admit_progress_effects.return_value = (
        ScheduledTaskProgressAdmission(
            status="superseded",
            tracker_current=False,
        )
    )

    execution = await service.execute_progress(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        run_id=_RUN_ID,
        binding_id=_BINDING_ID,
        mode=ExternalChannelActionMode.CONTINUE,
        message="Working on it.",
        title=None,
        tasks=None,
        files=(),
        file_storage=None,
        authority=None,
        provider_delivery_service=None,
        resolve_runtime_target=None,
    )

    assert execution.result is not None
    assert len(execution.result.outcomes) == 1
    assert execution.result.outcomes[0].status == "not_attempted"
    assert execution.result.outcomes[0].reason == "scheduled_progress_superseded"
    action_service.execute_binding_effect.assert_not_awaited()


@pytest.mark.asyncio
async def test_tracker_desired_revision_check_preserves_admitted_reply() -> None:
    service, progress_repository, _, action_service = _service()
    reply_plan = _plan(ExternalChannelDeliveryOperation.REPLY)
    tracker = _tracker_effect(_plan(ExternalChannelDeliveryOperation.PROGRESS_CREATE))
    progress_repository.prepare_progress.return_value = _prepared(
        state_revision=4,
        reply_plans=(reply_plan,),
        tracker=tracker,
    )
    progress_repository.admit_progress_effects.return_value = (
        ScheduledTaskProgressAdmission(
            status="admitted",
            tracker_current=False,
        )
    )
    action_service.execute_binding_effect.return_value = ProviderMutationOutcome(
        status="delivered",
        provider_message_key="slack:tenant:channel:reply",
        error_kind=None,
        error_summary=None,
    )

    execution = await service.execute_progress(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        run_id=_RUN_ID,
        binding_id=_BINDING_ID,
        mode=ExternalChannelActionMode.CONTINUE,
        message="Working on it.",
        title="Preparing the report…",
        tasks=[
            ExternalChannelWorkTask(
                id="collect",
                title="Collect data",
                status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
                details=None,
                output=None,
                sources=[],
            )
        ],
        files=(),
        file_storage=None,
        authority=None,
        provider_delivery_service=None,
        resolve_runtime_target=None,
    )

    assert execution.result is not None
    assert [outcome.status for outcome in execution.result.outcomes] == [
        "delivered",
        "not_attempted",
    ]
    assert execution.result.outcomes[1].reason == "scheduled_progress_superseded"
    action_service.execute_binding_effect.assert_awaited_once()
    progress_repository.settle_tracker.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_outcome", "projection_status", "result_status"),
    [
        (
            ProviderMutationOutcome(
                status="failed",
                provider_message_key=None,
                error_kind="provider_rejected",
                error_summary="The provider rejected the Tracker.",
            ),
            ExternalChannelWorkProjectionStatus.FAILED,
            "failed",
        ),
        (
            ProviderMutationOutcome(
                status="unknown",
                provider_message_key=None,
                error_kind="provider_ambiguous",
                error_summary="The Tracker outcome is unknown.",
            ),
            ExternalChannelWorkProjectionStatus.UNKNOWN,
            "unknown",
        ),
        (
            None,
            ExternalChannelWorkProjectionStatus.UNKNOWN,
            "not_attempted",
        ),
    ],
)
async def test_tracker_outcomes_settle_without_retry(
    provider_outcome: ProviderMutationOutcome | None,
    projection_status: ExternalChannelWorkProjectionStatus,
    result_status: str,
) -> None:
    service, progress_repository, _, action_service = _service()
    tracker = _tracker_effect(_plan(ExternalChannelDeliveryOperation.PROGRESS_CREATE))
    progress_repository.prepare_progress.return_value = _prepared(
        state_revision=4,
        tracker=tracker,
    )
    progress_repository.admit_progress_effects.return_value = (
        ScheduledTaskProgressAdmission(
            status="admitted",
            tracker_current=True,
        )
    )
    action_service.execute_binding_effect.return_value = provider_outcome

    execution = await service.execute_progress(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        run_id=_RUN_ID,
        binding_id=_BINDING_ID,
        mode=ExternalChannelActionMode.CONTINUE,
        message=None,
        title="Preparing the report…",
        tasks=[
            ExternalChannelWorkTask(
                id="collect",
                title="Collect data",
                status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
                details=None,
                output=None,
                sources=[],
            )
        ],
        files=(),
        file_storage=None,
        authority=None,
        provider_delivery_service=None,
        resolve_runtime_target=None,
    )

    assert execution.result is not None
    assert execution.result.outcomes[0].status == result_status
    progress_repository.settle_tracker.assert_awaited_once_with(
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        cycle_id=_CYCLE_ID,
        effect=tracker,
        status=projection_status,
        provider_message_key=None,
    )
    action_service.execute_binding_effect.assert_awaited_once_with(tracker.plan)


@pytest.mark.asyncio
async def test_cancellation_after_provider_return_does_not_replay_or_settle() -> None:
    service, progress_repository, _, action_service = _service()
    tracker = _tracker_effect(_plan(ExternalChannelDeliveryOperation.PROGRESS_CREATE))
    progress_repository.prepare_progress.return_value = _prepared(
        state_revision=4,
        tracker=tracker,
    )
    progress_repository.admit_progress_effects.return_value = (
        ScheduledTaskProgressAdmission(
            status="admitted",
            tracker_current=True,
        )
    )
    action_service.execute_binding_effect.return_value = ProviderMutationOutcome(
        status="delivered",
        provider_message_key="slack:tenant:channel:tracker",
        error_kind=None,
        error_summary=None,
    )
    settlement_entered = asyncio.Event()
    settlement_release = asyncio.Event()

    async def settle_tracker(**_: object) -> bool:
        settlement_entered.set()
        await settlement_release.wait()
        return True

    progress_repository.settle_tracker.side_effect = settle_tracker
    execution_task = asyncio.create_task(
        service.execute_progress(
            agent_id=_AGENT_ID,
            session_id=_SESSION_ID,
            run_id=_RUN_ID,
            binding_id=_BINDING_ID,
            mode=ExternalChannelActionMode.CONTINUE,
            message=None,
            title="Preparing the report…",
            tasks=[
                ExternalChannelWorkTask(
                    id="collect",
                    title="Collect data",
                    status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
                    details=None,
                    output=None,
                    sources=[],
                )
            ],
            files=(),
            file_storage=None,
            authority=None,
            provider_delivery_service=None,
            resolve_runtime_target=None,
        )
    )
    await settlement_entered.wait()

    execution_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await execution_task
    action_service.execute_binding_effect.assert_awaited_once_with(tracker.plan)
    assert progress_repository.settle_tracker.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsupported_mode",
    [
        ExternalChannelActionMode.FINISH,
        ExternalChannelActionMode.REQUEST_INPUT,
    ],
)
async def test_scheduled_non_continue_modes_and_wrong_binding_are_rejected(
    unsupported_mode: ExternalChannelActionMode,
) -> None:
    service, progress_repository, _, _ = _service()
    progress_repository.prepare_progress.side_effect = ValueError(
        "Scheduled Task channel_action only supports continue."
    )

    with pytest.raises(ValueError, match="only supports continue"):
        await service.execute_progress(
            agent_id=_AGENT_ID,
            session_id=_SESSION_ID,
            run_id=_RUN_ID,
            binding_id=_BINDING_ID,
            mode=unsupported_mode,
            message="Question or final reply.",
            title=None,
            tasks=None,
            files=(),
            file_storage=None,
            authority=None,
            provider_delivery_service=None,
            resolve_runtime_target=None,
        )
    progress_repository.prepare_progress.side_effect = ValueError(
        "Scheduled Task progress requires its exact current Binding."
    )
    with pytest.raises(ValueError, match="exact current Binding"):
        await service.execute_progress(
            agent_id=_AGENT_ID,
            session_id=_SESSION_ID,
            run_id=_RUN_ID,
            binding_id="x" * 32,
            mode=ExternalChannelActionMode.CONTINUE,
            message="Working.",
            title=None,
            tasks=None,
            files=(),
            file_storage=None,
            authority=None,
            provider_delivery_service=None,
            resolve_runtime_target=None,
        )

    progress_repository.admit_progress_effects.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_cleanup_runs_after_failed_publication() -> None:
    service, _, provider_repository, action_service = _service()
    reply_one = _plan(ExternalChannelDeliveryOperation.REPLY, payload={"part": 0})
    reply_two = _plan(ExternalChannelDeliveryOperation.REPLY, payload={"part": 1})
    cleanup = _plan(ExternalChannelDeliveryOperation.PROGRESS_DELETE)
    provider_repository.prepare_binding_reply_effects.return_value = (
        reply_one,
        reply_two,
    )
    provider_repository.prepare_binding_effect.return_value = cleanup
    action_service.execute_binding_effect.side_effect = [
        ProviderMutationOutcome(
            status="failed",
            provider_message_key=None,
            error_kind="reply_failed",
            error_summary="The first part failed.",
        ),
        ProviderMutationOutcome(
            status="delivered",
            provider_message_key="message-2",
            error_kind=None,
            error_summary=None,
        ),
        ProviderMutationOutcome(
            status="delivered",
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
        ),
    ]
    snapshot = ScheduledTaskTerminalEffectSnapshot(
        cycle_id=_CYCLE_ID,
        task_id="t" * 32,
        workspace_id="w" * 32,
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        binding_id=_BINDING_ID,
        status="finished",
        result="Completed the report.",
        tracker_desired_revision=1,
        tracker_projection_parts=(
            ScheduledTrackerProjectionPart(
                part_ordinal=0,
                desired_revision=1,
                status=ExternalChannelWorkProjectionStatus.PRESENT,
                provider_message_key="tracker-message",
            ),
        ),
    )
    manifest = ExternalChannelOutboundFileManifest(
        source=ExternalChannelOutboundFileSource.RUNTIME,
        path="/workspace/agent/report.png",
        filename="report.png",
        media_type="image/png",
        expected_size=128,
    )
    file_storage: FileStorage = MagicMock(spec=FileStorage)
    authority: SessionResourceAuthority = MagicMock(spec=SessionResourceAuthority)
    provider_delivery_service: RuntimeToProviderDeliveryExecutor = MagicMock(
        spec=RuntimeToProviderDeliveryExecutor
    )

    async def resolve_runtime_target() -> ServerToRuntimeTarget:
        raise AssertionError("The mocked action service must not resolve a Runtime.")

    outcomes = await service.execute_terminal(
        snapshot,
        files=(manifest,),
        file_storage=file_storage,
        authority=authority,
        provider_delivery_service=provider_delivery_service,
        resolve_runtime_target=resolve_runtime_target,
    )

    assert [outcome.operation for outcome in outcomes] == [
        ExternalChannelDeliveryOperation.REPLY,
        ExternalChannelDeliveryOperation.REPLY,
        ExternalChannelDeliveryOperation.PROGRESS_DELETE,
    ]
    assert outcomes[0].status == "failed"
    assert outcomes[2].status == "delivered"
    assert action_service.execute_binding_effect.await_args_list == [
        call(
            reply_one,
            file_storage=file_storage,
            agent_id=_AGENT_ID,
            session_id=_SESSION_ID,
            authority=authority,
            provider_delivery_service=provider_delivery_service,
            resolve_runtime_target=resolve_runtime_target,
        ),
        call(
            reply_two,
            file_storage=file_storage,
            agent_id=_AGENT_ID,
            session_id=_SESSION_ID,
            authority=authority,
            provider_delivery_service=provider_delivery_service,
            resolve_runtime_target=resolve_runtime_target,
        ),
        call(cleanup),
    ]
    _, reply_kwargs = provider_repository.prepare_binding_reply_effects.await_args
    assert reply_kwargs["binding_id"] == _BINDING_ID
    assert reply_kwargs["files"] == (manifest,)
    assert reply_kwargs["slack_reply_broadcast"] is True
    assert reply_kwargs["discord_forward_to_parent"] is True
