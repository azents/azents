"""Deterministic coordination without database, provider, or scheduler timing."""

import asyncio
import dataclasses
import datetime
from unittest.mock import AsyncMock, Mock, call

import pytest

from azents.core.agent_deletion import (
    AgentDeletionOwnershipLost,
    AgentDeletionParticipantFailure,
    AgentDeletionWaitReason,
)
from azents.core.agent_deletion_registry import get_agent_deletion_registry
from azents.repos.agent_decommission_operations import (
    AgentDecommissionOperationsRepository,
)
from azents.services.agent_decommission import (
    AgentDecommissionAdvanceResult,
    AgentDecommissionService,
)
from azents.services.agent_decommission_test import _job
from azents.services.agent_deletion import AgentDeletionExecution, AgentDeletionPipeline

_KEYS = tuple(item.key for item in get_agent_deletion_registry().participants)


@dataclasses.dataclass
class _Participant:
    key: str
    visited: list[str]
    outcome: AgentDeletionWaitReason | BaseException | None
    completes: bool

    async def run(self, execution: AgentDeletionExecution) -> None:
        self.visited.append(self.key)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        execution.wait_reason = self.outcome
        execution.completed = self.completes


@pytest.mark.parametrize("stop_index", range(len(_KEYS)))
@pytest.mark.parametrize("kind", ["failure", "cancel", "ownership", "attributed"])
async def test_pipeline_stops_at_exact_boundary(stop_index: int, kind: str) -> None:
    visited: list[str] = []
    original = OSError("object store unavailable")
    errors: dict[str, BaseException] = {
        "failure": original,
        "cancel": asyncio.CancelledError(),
        "ownership": AgentDeletionOwnershipLost("reclaimed"),
        "attributed": AgentDeletionParticipantFailure(
            participant_key="agent.runtime", phase="verify", error=original
        ),
    }
    error = errors[kind]
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    participants = tuple(
        _Participant(key, visited, error if index == stop_index else None, False)
        for index, key in enumerate(_KEYS)
    )
    pipeline = AgentDeletionPipeline(
        get_agent_deletion_registry(), tuple(reversed(participants)), operations
    )
    job = _job(job_id="failure")
    expected_type = (
        AgentDeletionParticipantFailure if kind == "failure" else type(error)
    )
    with pytest.raises(expected_type) as caught:
        await pipeline.advance(job=job, lease_owner="owner")
    if kind == "failure":
        assert isinstance(caught.value, AgentDeletionParticipantFailure)
        assert caught.value.error is original
        assert caught.value.__cause__ is original
        assert caught.value.boundary_key == f"{_KEYS[stop_index]}/cleanup"
    else:
        assert caught.value is error
    assert visited == list(_KEYS[: stop_index + 1])
    assert operations.clear_failure_boundary.await_args_list == [
        call(job=job, lease_owner="owner", boundary_key=f"{key}/cleanup")
        for key in _KEYS[:stop_index]
    ]


@pytest.mark.parametrize("reason", list(AgentDeletionWaitReason))
@pytest.mark.parametrize("stop_index", range(len(_KEYS)))
async def test_wait_preserves_current_obligation_and_skips_later_work(
    reason: AgentDeletionWaitReason, stop_index: int
) -> None:
    visited: list[str] = []
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    participants = tuple(
        _Participant(key, visited, reason if index == stop_index else None, False)
        for index, key in enumerate(_KEYS)
    )
    result = await AgentDeletionPipeline(
        get_agent_deletion_registry(), participants, operations
    ).advance(job=_job(job_id="waiting"), lease_owner="owner")
    assert result.wait_reason is reason
    assert not result.completed
    assert visited == list(_KEYS[: stop_index + 1])
    assert [
        item.kwargs["boundary_key"]
        for item in operations.clear_failure_boundary.await_args_list
    ] == [f"{key}/cleanup" for key in _KEYS[:stop_index]]


async def test_replay_has_no_post_completion_write() -> None:
    visited: list[str] = []
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    participants = tuple(
        _Participant(key, visited, None, key == _KEYS[-1]) for key in reversed(_KEYS)
    )
    pipeline = AgentDeletionPipeline(
        get_agent_deletion_registry(), participants, operations
    )
    for attempt in (1, 2):
        result = await pipeline.advance(
            job=_job(job_id="replay", attempt_count=attempt), lease_owner="owner"
        )
        assert result.completed and result.wait_reason is None
    assert visited == list(_KEYS) * 2
    assert [
        item.kwargs["boundary_key"]
        for item in operations.clear_failure_boundary.await_args_list
    ] == [f"{key}/cleanup" for key in _KEYS[:-1]] * 2


@pytest.mark.parametrize("invalid", ["missing", "extra", "duplicate"])
async def test_invalid_composition_has_no_effects(invalid: str) -> None:
    visited: list[str] = []
    keys = list(_KEYS)
    if invalid == "missing":
        keys.pop()
    elif invalid == "extra":
        keys.append("unknown")
    else:
        keys.append(keys[0])
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    with pytest.raises(ValueError, match="handlers"):
        await AgentDeletionPipeline(
            get_agent_deletion_registry(),
            tuple(_Participant(key, visited, None, False) for key in keys),
            operations,
        ).advance(job=_job(job_id="invalid"), lease_owner="owner")
    assert visited == []
    operations.clear_failure_boundary.assert_not_awaited()


async def test_reclaim_during_recovery_stops_before_next_external_effect() -> None:
    visited: list[str] = []
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    lost = AgentDeletionOwnershipLost("new attempt owns the job")
    operations.clear_failure_boundary.side_effect = lost
    with pytest.raises(AgentDeletionOwnershipLost) as caught:
        await AgentDeletionPipeline(
            get_agent_deletion_registry(),
            tuple(_Participant(key, visited, None, False) for key in _KEYS),
            operations,
        ).advance(job=_job(job_id="reclaimed"), lease_owner="owner")
    assert caught.value is lost
    assert visited == [_KEYS[0]]


@pytest.mark.parametrize("reason", list(AgentDeletionWaitReason))
async def test_scheduler_waits_without_failure_record(
    reason: AgentDeletionWaitReason,
) -> None:
    now = datetime.datetime(2026, 10, 20, tzinfo=datetime.UTC)
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    job = _job(job_id="wait", attempt_count=3)
    operations.claim_due.side_effect = [job, None]
    operations.schedule_wait.return_value = True
    service = Mock(spec=AgentDecommissionService)
    service.clock = Mock()
    service.clock.now.return_value = now
    service.operation_repository = operations
    service._advance = AsyncMock(
        return_value=AgentDecommissionAdvanceResult(False, reason)
    )
    service._retry_delay = AgentDecommissionService._retry_delay
    summary = await AgentDecommissionService.decommission_once(
        service, lease_owner="owner", deadline=now + datetime.timedelta(minutes=5)
    )
    assert summary.completed_count == 0
    assert summary.claimed_count == 1
    service._retry.assert_not_called()
    operations.mark_retry.assert_not_awaited()
    if reason is AgentDeletionWaitReason.RETENTION:
        operations.schedule_wait.assert_not_awaited()
        assert summary.waiting_retention_count == 1
    else:
        operations.schedule_wait.assert_awaited_once_with(
            job=job,
            lease_owner="owner",
            now=now,
            next_attempt_at=now + datetime.timedelta(minutes=4),
        )
        assert summary.retry_scheduled_count == 1


@pytest.mark.parametrize(
    "attempt,minutes", [(0, 1), (1, 1), (2, 2), (5, 16), (6, 30), (100, 30)]
)
def test_retry_delay_is_bounded(attempt: int, minutes: int) -> None:
    assert AgentDecommissionService._retry_delay(attempt) == datetime.timedelta(
        minutes=minutes
    )
