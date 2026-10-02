"""Pure lifecycle orchestration tests using completed-operation mocks."""

import dataclasses
from datetime import UTC, datetime
from unittest.mock import MagicMock, call, create_autospec

import pytest

from azents.broker.types import SessionBroker
from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.inference_profile import RequestedInferenceProfile
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_execution.data import PendingCommandSnapshot
from azents.repos.worker_session import WorkerSessionOperationRepository
from azents.repos.worker_session_data import (
    CanonicalExecutionWorkDriftError,
    WorkerIdleDisposition,
    WorkerIdleTransition,
)
from azents.worker.session.lifecycle import SessionLifecycleService


@dataclasses.dataclass(frozen=True)
class LifecycleFixture:
    """Typed production collaborators and their independently inspectable mocks."""

    service: SessionLifecycleService
    repository: MagicMock
    broker: MagicMock
    timeline: MagicMock


def lifecycle_fixture() -> LifecycleFixture:
    """Autospec completed operations, never a fake SQL session or manager."""
    repository_mock = create_autospec(WorkerSessionOperationRepository, instance=True)
    broker_mock = create_autospec(SessionBroker, instance=True)
    repository: WorkerSessionOperationRepository = repository_mock
    broker: SessionBroker = broker_mock
    timeline = MagicMock()
    timeline.attach_mock(repository_mock, "repository")
    timeline.attach_mock(broker_mock, "broker")
    return LifecycleFixture(
        SessionLifecycleService(broker=broker, repository=repository),
        repository_mock,
        broker_mock,
        timeline,
    )


@pytest.mark.asyncio
async def test_heartbeat_completes_database_before_broker_lease() -> None:
    """The only service-owned heartbeat ordering is completed DB then broker."""
    fixture = lifecycle_fixture()
    await fixture.service.heartbeat_session("session", owner_generation=3)
    assert fixture.timeline.mock_calls == [
        call.repository.heartbeat_session("session", owner_generation=3),
        call.broker.renew_session_ttl("session"),
    ]


@pytest.mark.asyncio
async def test_failed_heartbeat_does_not_renew_broker_lease() -> None:
    fixture = lifecycle_fixture()
    fixture.repository.heartbeat_session.side_effect = RuntimeError("DB failure")
    with pytest.raises(RuntimeError, match="DB failure"):
        await fixture.service.heartbeat_session("session", owner_generation=3)
    fixture.broker.renew_session_ttl.assert_not_awaited()


@pytest.mark.parametrize("disposition", list(WorkerIdleDisposition))
@pytest.mark.asyncio
async def test_idle_consumes_completed_repository_outcome(
    disposition: WorkerIdleDisposition,
) -> None:
    """DB predicates belong to repository tests; service maps detached outcomes."""
    fixture = lifecycle_fixture()
    fixture.repository.mark_session_idle.return_value = WorkerIdleTransition(
        disposition=disposition,
        command_id="command"
        if disposition is WorkerIdleDisposition.COMMAND_PENDING
        else None,
        run_id="run" if disposition is WorkerIdleDisposition.RUN_ACTIVE else None,
    )
    result = await fixture.service.mark_session_idle("session", owner_generation=3)
    assert result is (disposition is WorkerIdleDisposition.IDLE)
    fixture.repository.mark_session_idle.assert_awaited_once_with(
        "session", owner_generation=3
    )
    fixture.broker.renew_session_ttl.assert_not_awaited()


@pytest.mark.asyncio
async def test_idle_propagates_completed_operation_failure() -> None:
    fixture = lifecycle_fixture()
    fixture.repository.mark_session_idle.side_effect = RuntimeError("DB failure")
    with pytest.raises(RuntimeError, match="DB failure"):
        await fixture.service.mark_session_idle("session", owner_generation=3)


@pytest.mark.parametrize("effect", ["release", "activity"])
@pytest.mark.asyncio
async def test_owner_validation_precedes_external_effect(effect: str) -> None:
    fixture = lifecycle_fixture()
    if effect == "release":
        await fixture.service.release_owned_session_lock("session", owner_generation=3)
        expected = call.broker.release_session_lock("session")
    else:
        await fixture.service.set_session_activity(
            "session", owner_generation=3, run_id="run", phase=AgentRunPhase.IDLE
        )
        expected = call.broker.set_session_activity(
            "session", owner_generation=3, run_id="run", phase=AgentRunPhase.IDLE
        )
    assert fixture.timeline.mock_calls == [
        call.repository.assert_current_owner_generation("session", owner_generation=3),
        expected,
    ]


@pytest.mark.asyncio
async def test_stale_generation_blocks_external_effect() -> None:
    fixture = lifecycle_fixture()
    fixture.repository.assert_current_owner_generation.side_effect = (
        CanonicalExecutionOwnerGenerationStaleError("Session owner generation is stale")
    )
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await fixture.service.release_owned_session_lock("session", owner_generation=3)
    fixture.broker.release_session_lock.assert_not_awaited()


@pytest.mark.parametrize("parent_id", [None, "parent"])
@pytest.mark.asyncio
async def test_parent_notification_follows_completed_routing_read(
    parent_id: str | None,
) -> None:
    fixture = lifecycle_fixture()
    fixture.repository.parent_result_activity_session_id.return_value = parent_id
    await fixture.service.notify_parent_result_activity("run")
    fixture.repository.parent_result_activity_session_id.assert_awaited_once_with("run")
    if parent_id is not None:
        assert fixture.timeline.mock_calls == [
            call.repository.parent_result_activity_session_id("run"),
            call.broker.notify_mailbox_activity(parent_id),
        ]
    else:
        fixture.broker.notify_mailbox_activity.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_command_delegates_exact_snapshot_and_drift_error() -> None:
    fixture = lifecycle_fixture()
    command = PendingCommandSnapshot(
        id="command",
        name="compact",
        payload={},
        requester_user_id=None,
        created_at=datetime.now(UTC),
    )
    fixture.repository.validate_pending_command.side_effect = (
        CanonicalExecutionWorkDriftError("Canonical pending command changed")
    )
    with pytest.raises(CanonicalExecutionWorkDriftError):
        await fixture.service.validate_pending_command(
            "session", owner_generation=3, command=command
        )
    fixture.repository.validate_pending_command.assert_awaited_once_with(
        "session", owner_generation=3, command=command
    )


@pytest.mark.parametrize("status", [AgentRunStatus.CANCELLED, AgentRunStatus.COMPLETED])
@pytest.mark.asyncio
async def test_bridge_delegates_completed_atomic_operation(
    status: AgentRunStatus,
) -> None:
    fixture = lifecycle_fixture()
    fixture.repository.complete_bridge_predecessor_run.return_value = status
    assert (
        await fixture.service.complete_bridge_predecessor_run(
            "session", owner_generation=3, run_id="run"
        )
        is status
    )
    fixture.repository.complete_bridge_predecessor_run.assert_awaited_once_with(
        "session", owner_generation=3, run_id="run"
    )


@pytest.mark.asyncio
async def test_activation_delegates_profile_phase_and_result() -> None:
    fixture = lifecycle_fixture()
    profile = RequestedInferenceProfile(
        model_target_label="default",
        reasoning_effort=None,
        enabled_execution_options=[],
    )
    result = await fixture.service.activate_pending_agent_run(
        "session",
        owner_generation=3,
        run_id="run",
        initial_phase=AgentRunPhase.COMPACTING,
        requested_profile=profile,
    )
    assert result is fixture.repository.activate_pending_agent_run.return_value
    fixture.repository.activate_pending_agent_run.assert_awaited_once_with(
        "session",
        owner_generation=3,
        run_id="run",
        initial_phase=AgentRunPhase.COMPACTING,
        requested_profile=profile,
    )
