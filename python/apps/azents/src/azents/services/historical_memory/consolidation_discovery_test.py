"""System policy is captured coherently at each consolidation dispatch pass."""

import datetime
from unittest.mock import AsyncMock, Mock, create_autospec

import pytest

import azents.services.historical_memory.consolidation_discovery as discovery_module
from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationUnitKey,
)
from azents.core.historical_memory_system_setting import HistoricalMemoryExecutionConfig
from azents.job_runtime.types import JobRequest
from azents.repos.historical_memory_consolidation.discovery import (
    ConsolidationDiscoveryRepository,
)
from azents.services.historical_memory.consolidation_discovery import (
    HistoricalMemoryConsolidationDiscoveryService,
)
from azents.services.historical_memory.constants import (
    HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY,
)
from azents.services.historical_memory.execution_policy import (
    HistoricalMemoryExecutionPolicyService,
)


def _keys() -> list[ConsolidationUnitKey]:
    return [
        ConsolidationUnitKey(
            workspace_id="w" * 32,
            agent_id="a" * 32,
            scope=ConsolidationScope.TEAM,
            associated_user_id=None,
        ),
        ConsolidationUnitKey(
            workspace_id="w" * 32,
            agent_id="a" * 32,
            scope=ConsolidationScope.USER,
            associated_user_id="u" * 32,
        ),
    ]


def _freeze_now(monkeypatch: pytest.MonkeyPatch) -> datetime.datetime:
    now = datetime.datetime(2026, 10, 4, 12, tzinfo=datetime.UTC)

    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz: datetime.tzinfo | None = None) -> datetime.datetime:
            assert tz is datetime.UTC
            return now

    monkeypatch.setattr(discovery_module.datetime, "datetime", FixedDateTime)
    return now


async def test_dispatch_captures_system_cutoffs_for_all_exact_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seven-turn/thirteen-second policy controls both deadline and payload."""
    keys = _keys()
    repository = create_autospec(
        ConsolidationDiscoveryRepository, instance=True, spec_set=True
    )
    repository.list_due = AsyncMock(return_value=keys)
    monkeypatch.setattr(
        discovery_module, "ConsolidationDiscoveryRepository", lambda _: repository
    )
    runtime = AsyncMock()
    policy = create_autospec(
        HistoricalMemoryExecutionPolicyService, instance=True, spec_set=True
    )
    policy.resolve = AsyncMock(
        return_value=HistoricalMemoryExecutionConfig(max_turns=7, timeout_seconds=13)
    )
    service = HistoricalMemoryConsolidationDiscoveryService(
        session_manager=Mock(),
        job_runtime=runtime,
        execution_settings=policy,
    )
    now = _freeze_now(monkeypatch)

    assert await service.dispatch_pending(agent_id="a" * 32) == 2

    repository.list_due.assert_awaited_once_with(agent_id="a" * 32, limit=25)
    policy.resolve.assert_awaited_once_with()
    assert runtime.submit.await_count == 2
    for key, call in zip(keys, runtime.submit.await_args_list, strict=True):
        request = call.args[0]
        assert isinstance(request, JobRequest)
        assert request.handler_key == HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY
        owner = key.associated_user_id or "team"
        assert (
            request.execution_key
            == f"historical-consolidation:{key.workspace_id}:{key.agent_id}:"
            f"{key.scope.value}:{owner}"
        )
        assert request.deadline == now + datetime.timedelta(seconds=13)
        assert request.payload == {
            "unit": key.model_dump(mode="json"),
            "execution_policy": {"max_turns": 7, "timeout_seconds": 13},
        }


async def test_later_dispatch_observes_policy_change_without_mutating_prior_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each pass resolves current policy instead of carrying a process snapshot."""
    key = _keys()[0]
    repository = create_autospec(
        ConsolidationDiscoveryRepository, instance=True, spec_set=True
    )
    repository.list_due = AsyncMock(return_value=[key])
    monkeypatch.setattr(
        discovery_module, "ConsolidationDiscoveryRepository", lambda _: repository
    )
    policies = [
        HistoricalMemoryExecutionConfig(max_turns=None, timeout_seconds=5),
        HistoricalMemoryExecutionConfig(max_turns=7, timeout_seconds=13),
    ]
    policy = create_autospec(
        HistoricalMemoryExecutionPolicyService, instance=True, spec_set=True
    )
    policy.resolve = AsyncMock(side_effect=policies)
    runtime = AsyncMock()
    service = HistoricalMemoryConsolidationDiscoveryService(
        session_manager=Mock(),
        job_runtime=runtime,
        execution_settings=policy,
    )
    now = _freeze_now(monkeypatch)

    assert await service.dispatch_pending(agent_id=None) == 1
    assert await service.dispatch_pending(agent_id=None) == 1

    assert policy.resolve.await_count == 2
    for expected, call in zip(policies, runtime.submit.await_args_list, strict=True):
        request = call.args[0]
        assert isinstance(request, JobRequest)
        assert request.deadline == now + datetime.timedelta(
            seconds=expected.timeout_seconds
        )
        assert request.payload["execution_policy"] == expected.model_dump(mode="json")
    first = runtime.submit.await_args_list[0].args[0]
    assert first.payload["execution_policy"] == {
        "max_turns": None,
        "timeout_seconds": 5,
    }


async def test_empty_pass_submits_no_runtime_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = create_autospec(
        ConsolidationDiscoveryRepository, instance=True, spec_set=True
    )
    repository.list_due = AsyncMock(return_value=[])
    monkeypatch.setattr(
        discovery_module, "ConsolidationDiscoveryRepository", lambda _: repository
    )
    policy = create_autospec(
        HistoricalMemoryExecutionPolicyService, instance=True, spec_set=True
    )
    policy.resolve = AsyncMock(return_value=HistoricalMemoryExecutionConfig())
    runtime = AsyncMock()
    service = HistoricalMemoryConsolidationDiscoveryService(
        session_manager=Mock(),
        job_runtime=runtime,
        execution_settings=policy,
    )
    assert await service.dispatch_pending(agent_id=None) == 0
    runtime.submit.assert_not_awaited()


async def test_policy_failure_cannot_dispatch_default_substitute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = create_autospec(
        ConsolidationDiscoveryRepository, instance=True, spec_set=True
    )
    repository.list_due = AsyncMock(return_value=_keys())
    monkeypatch.setattr(
        discovery_module, "ConsolidationDiscoveryRepository", lambda _: repository
    )
    policy = create_autospec(
        HistoricalMemoryExecutionPolicyService, instance=True, spec_set=True
    )
    policy.resolve = AsyncMock(side_effect=RuntimeError("settings unavailable"))
    runtime = AsyncMock()
    service = HistoricalMemoryConsolidationDiscoveryService(
        session_manager=Mock(),
        job_runtime=runtime,
        execution_settings=policy,
    )
    with pytest.raises(RuntimeError, match="settings unavailable"):
        await service.dispatch_pending(agent_id=None)
    runtime.submit.assert_not_awaited()
