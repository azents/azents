"""Scheduled-owned External Channel orchestration tests."""

import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import ANY, AsyncMock, call

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
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import (
    ScheduledTaskCycleRecord,
    ScheduledTaskCycleState,
    ScheduledTrackerProjectionPart,
)
from azents.runtime.transfer.runtime_to_provider import (
    RuntimeToProviderDeliveryExecutor,
)
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
    RuntimeTargetResolver,
)
from azents.services.external_channel.provider_effect import (
    ProviderEffectPlan,
    ProviderMutationOutcome,
    ProviderOperationKey,
    ProviderTarget,
)
from azents.services.file_storage import FileStorage
from azents.services.scheduled_task.channel import ScheduledTaskChannelService
from azents.services.scheduled_task.terminal import (
    ScheduledTaskTerminalEffectSnapshot,
)
from azents.services.session_resource_authority import SessionResourceAuthority

_NOW = datetime.datetime(2026, 8, 16, 12, 0, tzinfo=datetime.UTC)
_AGENT_ID = "a" * 32
_SESSION_ID = "s" * 32
_CYCLE_ID = "c" * 32
_BINDING_ID = "b" * 32
_RUN_ID = "r" * 32


@asynccontextmanager
async def _session_manager() -> AsyncIterator[AsyncSession]:
    yield cast(AsyncSession, object())


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


def _service() -> tuple[
    ScheduledTaskChannelService,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
]:
    run_repository = AsyncMock()
    cycle_repository = AsyncMock()
    provider_repository = AsyncMock()
    action_service = AsyncMock()
    config = cast(
        Config,
        SimpleNamespace(
            auth=SimpleNamespace(jwt=SimpleNamespace(secret_key="test-secret"))
        ),
    )
    service = ScheduledTaskChannelService(
        session_manager=cast(SessionManager[AsyncSession], _session_manager),
        run_repository=cast(AgentRunRepository, run_repository),
        cycle_repository=cast(ScheduledTaskCycleRepository, cycle_repository),
        provider_repository=cast(ExternalChannelWorkRepository, provider_repository),
        action_service=cast(ExternalChannelActionService, action_service),
        config=config,
    )
    return (
        service,
        run_repository,
        cycle_repository,
        provider_repository,
        action_service,
    )


@pytest.mark.asyncio
async def test_initial_tracker_uses_scheduled_task_activity_copy() -> None:
    service, _, cycle_repository, provider_repository, action_service = _service()
    cycle_repository.get_started.return_value = _cycle()
    cycle_repository.claim_tracker_projection.return_value = _cycle(version=3)
    plan = _plan(ExternalChannelDeliveryOperation.PROGRESS_CREATE)
    provider_repository.prepare_binding_effect.return_value = plan
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
    _, kwargs = provider_repository.prepare_binding_effect.await_args
    assert kwargs["slack_payload"]["text"] == (
        "Agent is running scheduled task ‘Daily report’…"
    )
    assert kwargs["slack_payload"]["blocks"][0]["title"] == (
        "Agent is running scheduled task ‘Daily report’…"
    )
    assert kwargs["discord_payload"]["embeds"][0]["description"] == (
        "◉ Agent is running scheduled task ‘Daily report’…"
    )
    assert "Prepare the report." not in str(kwargs)
    cycle_repository.settle_tracker_projection.assert_awaited_once()


@pytest.mark.asyncio
async def test_registration_uses_exact_binding_and_returns_immediate_outcome() -> None:
    service, _, _, provider_repository, action_service = _service()
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
    service, _, _, provider_repository, action_service = _service()
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
    service, _, _, provider_repository, action_service = _service()

    outcome = await service.execute_deletion(
        dataclasses.replace(_task(), binding_id=None)
    )

    assert outcome is None
    provider_repository.prepare_binding_effect.assert_not_awaited()
    action_service.execute_binding_effect.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduled_continue_updates_and_settles_tracker() -> None:
    service, run_repository, cycle_repository, provider_repository, action_service = (
        _service()
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
    cycle_repository.update_progress.assert_awaited_once_with(
        ANY,
        record=initial,
        progress_title="Preparing the report…",
        ordered_tasks=["Collect data"],
    )
    _, settle_kwargs = cycle_repository.settle_tracker_projection.await_args
    assert settle_kwargs["expected_desired_revision"] == 1
    assert settle_kwargs["status"] is ExternalChannelWorkProjectionStatus.PRESENT
    assert settle_kwargs["provider_message_key"] == ("slack:tenant:channel:tracker")


@pytest.mark.asyncio
async def test_terminalization_winning_after_progress_commit_suppresses_effects() -> (
    None
):
    """A deleted cycle cannot fall through or publish its prepared reply."""
    service, run_repository, cycle_repository, provider_repository, action_service = (
        _service()
    )
    run_repository.get_by_id.return_value = SimpleNamespace(
        session_id=_SESSION_ID,
        scheduled_task_cycle_id=_CYCLE_ID,
    )
    cycle_repository.lock.side_effect = [_cycle(), None]
    reply_plan = _plan(ExternalChannelDeliveryOperation.REPLY)
    provider_repository.prepare_binding_reply_effects.return_value = (reply_plan,)

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
    service, run_repository, cycle_repository, provider_repository, action_service = (
        _service()
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
    newer = _cycle(desired_revision=2, version=5)
    run_repository.get_by_id.return_value = SimpleNamespace(
        session_id=_SESSION_ID,
        scheduled_task_cycle_id=_CYCLE_ID,
    )
    cycle_repository.lock.side_effect = [initial, newer]
    cycle_repository.update_progress.return_value = updated
    cycle_repository.claim_tracker_projection.return_value = claimed
    reply_plan = _plan(ExternalChannelDeliveryOperation.REPLY)
    tracker_plan = _plan(ExternalChannelDeliveryOperation.PROGRESS_CREATE)
    provider_repository.prepare_binding_reply_effects.return_value = (reply_plan,)
    provider_repository.prepare_binding_effect.return_value = tracker_plan
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
    assert [outcome.reason for outcome in execution.result.outcomes] == [
        "scheduled_progress_superseded",
        "scheduled_progress_superseded",
    ]
    assert all(
        outcome.status == "not_attempted" for outcome in execution.result.outcomes
    )
    action_service.execute_binding_effect.assert_not_awaited()
    cycle_repository.settle_tracker_projection.assert_not_awaited()


@pytest.mark.asyncio
async def test_newer_progress_revision_suppresses_message_only_reply() -> None:
    """Message-only publication is fenced by the cycle version it observed."""
    service, run_repository, cycle_repository, provider_repository, action_service = (
        _service()
    )
    run_repository.get_by_id.return_value = SimpleNamespace(
        session_id=_SESSION_ID,
        scheduled_task_cycle_id=_CYCLE_ID,
    )
    cycle_repository.lock.side_effect = [_cycle(version=2), _cycle(version=3)]
    reply_plan = _plan(ExternalChannelDeliveryOperation.REPLY)
    provider_repository.prepare_binding_reply_effects.return_value = (reply_plan,)

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
async def test_scheduled_terminal_modes_and_wrong_binding_are_rejected() -> None:
    service, run_repository, cycle_repository, provider_repository, _ = _service()
    run_repository.get_by_id.return_value = SimpleNamespace(
        session_id=_SESSION_ID,
        scheduled_task_cycle_id=_CYCLE_ID,
    )
    cycle_repository.lock.return_value = _cycle()

    with pytest.raises(ValueError, match="only supports continue"):
        await service.execute_progress(
            agent_id=_AGENT_ID,
            session_id=_SESSION_ID,
            run_id=_RUN_ID,
            binding_id=_BINDING_ID,
            mode=ExternalChannelActionMode.FINISH,
            message="Done.",
            title=None,
            tasks=None,
            files=(),
            file_storage=None,
            authority=None,
            provider_delivery_service=None,
            resolve_runtime_target=None,
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

    provider_repository.prepare_binding_reply_effects.assert_not_awaited()
    cycle_repository.update_progress.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_cleanup_runs_after_failed_publication() -> None:
    service, _, _, provider_repository, action_service = _service()
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
    file_storage = cast(FileStorage, object())
    authority = cast(SessionResourceAuthority, object())
    provider_delivery_service = object()
    resolve_runtime_target = object()

    outcomes = await service.execute_terminal(
        snapshot,
        files=(manifest,),
        file_storage=file_storage,
        authority=authority,
        provider_delivery_service=cast(
            RuntimeToProviderDeliveryExecutor,
            provider_delivery_service,
        ),
        resolve_runtime_target=cast(
            RuntimeTargetResolver,
            resolve_runtime_target,
        ),
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
