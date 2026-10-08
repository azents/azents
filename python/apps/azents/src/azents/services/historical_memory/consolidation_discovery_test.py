"""Capture admitted policy and route common Sessions after durable admission."""

import datetime
from unittest.mock import AsyncMock, create_autospec

import pytest
import sqlalchemy as sa

import azents.services.historical_memory.consolidation_discovery as discovery_module
from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationUnitKey,
    FreshMemoryAdmission,
    MemoryExecutionBinding,
)
from azents.core.historical_memory_system_setting import HistoricalMemoryExecutionConfig
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.discovery import (
    ConsolidationDiscoveryRepository,
)
from azents.repos.historical_memory_consolidation.execution import (
    MemoryExecutionRepository,
)
from azents.services.historical_memory.consolidation_discovery import (
    HistoricalMemoryConsolidationDiscoveryService,
)
from azents.services.historical_memory.execution_policy import (
    HistoricalMemoryExecutionPolicyService,
)
from azents.testing.consolidation import (
    memory_execution_repository,
    seed_consolidation_corpus,
)


def _keys() -> list[ConsolidationUnitKey]:
    return [
        ConsolidationUnitKey(
            workspace_id="w" * 32,
            agent_id="a" * 32,
            scope=scope,
            associated_user_id=user,
        )
        for scope, user in [
            (ConsolidationScope.TEAM, None),
            (ConsolidationScope.USER, "u" * 32),
        ]
    ]


def _binding(
    key: ConsolidationUnitKey, admission: FreshMemoryAdmission
) -> MemoryExecutionBinding:
    return MemoryExecutionBinding(
        unit_id="b" * 32,
        unit=key,
        session_id=("c" if key.associated_user_id is None else "d") * 32,
        deadline_at=admission.deadline_at,
        execution_policy=admission.execution_policy,
        started_turns=0,
        accepted=None,
    )


def _freeze_now(monkeypatch: pytest.MonkeyPatch) -> datetime.datetime:
    now = datetime.datetime(2026, 10, 4, 12, tzinfo=datetime.UTC)

    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz: datetime.tzinfo | None = None) -> datetime.datetime:
            assert tz is datetime.UTC
            return now

    monkeypatch.setattr(discovery_module.datetime, "datetime", FixedDateTime)
    return now


async def test_dispatch_captures_policy_and_routes_only_common_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = _keys()
    discovery = create_autospec(
        ConsolidationDiscoveryRepository, instance=True, spec_set=True
    )
    discovery.list_due = AsyncMock(return_value=keys)
    executions = create_autospec(
        MemoryExecutionRepository, instance=True, spec_set=True
    )

    async def ensure(
        key: ConsolidationUnitKey, *, admission: FreshMemoryAdmission
    ) -> MemoryExecutionBinding:
        return _binding(key, admission)

    executions.ensure_execution = AsyncMock(side_effect=ensure)
    broker = create_autospec(SessionBroker, instance=True, spec_set=True)
    policy = create_autospec(
        HistoricalMemoryExecutionPolicyService, instance=True, spec_set=True
    )
    policy.resolve = AsyncMock(
        return_value=HistoricalMemoryExecutionConfig(max_turns=7, timeout_seconds=13)
    )
    service = HistoricalMemoryConsolidationDiscoveryService(
        discovery, executions, broker, policy
    )
    now = _freeze_now(monkeypatch)
    assert await service.dispatch_pending(agent_id="a" * 32) == 2
    discovery.list_due.assert_awaited_once_with(agent_id="a" * 32, limit=25)
    policy.resolve.assert_awaited_once_with()
    for key, call, route in zip(
        keys,
        executions.ensure_execution.await_args_list,
        broker.send_message.await_args_list,
        strict=True,
    ):
        assert call.args == (key,)
        admission = call.kwargs["admission"]
        assert admission == FreshMemoryAdmission(
            now + datetime.timedelta(seconds=13),
            HistoricalMemoryExecutionConfig(max_turns=7, timeout_seconds=13),
        )
        assert route.args == (
            SessionWakeUp(session_id=_binding(key, admission).session_id),
        )


async def test_policy_failure_cannot_dispatch_substitute() -> None:
    discovery = create_autospec(
        ConsolidationDiscoveryRepository, instance=True, spec_set=True
    )
    discovery.list_due = AsyncMock(return_value=_keys())
    executions = create_autospec(
        MemoryExecutionRepository, instance=True, spec_set=True
    )
    broker = create_autospec(SessionBroker, instance=True, spec_set=True)
    policy = create_autospec(
        HistoricalMemoryExecutionPolicyService, instance=True, spec_set=True
    )
    policy.resolve = AsyncMock(side_effect=RuntimeError("settings unavailable"))
    with pytest.raises(RuntimeError, match="settings unavailable"):
        await HistoricalMemoryConsolidationDiscoveryService(
            discovery, executions, broker, policy
        ).dispatch_pending(agent_id=None)
    executions.ensure_execution.assert_not_awaited()
    broker.send_message.assert_not_awaited()


async def test_empty_pass_routes_no_work() -> None:
    discovery = create_autospec(
        ConsolidationDiscoveryRepository, instance=True, spec_set=True
    )
    discovery.list_due = AsyncMock(return_value=[])
    executions = create_autospec(
        MemoryExecutionRepository, instance=True, spec_set=True
    )
    broker = create_autospec(SessionBroker, instance=True, spec_set=True)
    policy = create_autospec(
        HistoricalMemoryExecutionPolicyService, instance=True, spec_set=True
    )
    policy.resolve = AsyncMock(return_value=HistoricalMemoryExecutionConfig())
    assert (
        await HistoricalMemoryConsolidationDiscoveryService(
            discovery, executions, broker, policy
        ).dispatch_pending(agent_id=None)
        == 0
    )
    executions.ensure_execution.assert_not_awaited()
    broker.send_message.assert_not_awaited()


async def test_real_admission_commits_before_routing_and_creates_no_public_profile(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    executions = memory_execution_repository(rdb_session_manager)
    broker = create_autospec(SessionBroker, instance=True, spec_set=True)
    policy = create_autospec(
        HistoricalMemoryExecutionPolicyService, instance=True, spec_set=True
    )
    policy.resolve = AsyncMock(
        return_value=HistoricalMemoryExecutionConfig(max_turns=7, timeout_seconds=60)
    )
    routed: list[str] = []

    async def route(message: SessionWakeUp) -> None:
        async with rdb_session_manager() as session:
            row = await session.read_session.get(RDBAgentSession, message.session_id)
            assert row is not None
            assert (
                await session.read_session.get(RDBConversation, message.session_id)
                is None
            )
            assert (
                await session.read_session.scalar(
                    sa.select(RDBAgentRun.id).where(
                        RDBAgentRun.session_id == message.session_id
                    )
                )
                is None
            )
        binding = await executions.load_binding(message.session_id)
        assert (
            binding is not None
            and binding.started_turns == 0
            and binding.accepted is None
        )
        routed.append(message.session_id)

    broker.send_message = AsyncMock(side_effect=route)
    service = HistoricalMemoryConsolidationDiscoveryService(
        ConsolidationDiscoveryRepository(rdb_session_manager),
        executions,
        broker,
        policy,
    )
    dispatched = await service.dispatch_pending(agent_id=corpus.team.agent_id)
    assert dispatched == len(routed) and dispatched > 0
    prior = tuple(routed)
    assert await service.dispatch_pending(agent_id=corpus.team.agent_id) == len(prior)
    assert tuple(routed[len(prior) :]) == prior
