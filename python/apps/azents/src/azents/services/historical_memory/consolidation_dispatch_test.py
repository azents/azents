"""Common dispatch identity and canonical usage, without a second request journal."""

import asyncio

import pytest

from azents.core.historical_memory_consolidation import MemoryExecutionAuthorityError
from azents.engine.events.types import TokenUsagePayload
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.services.historical_memory.consolidation_dispatch import (
    ConsolidationDispatchAdmission,
)
from azents.services.historical_memory.consolidation_host_test import (
    _host,
    _never_stop,
    _ScriptedModel,
    _stored_events,
)


async def test_dispatch_uses_actual_common_session_run_and_usage(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    host = await _host(
        rdb_session_manager, _ScriptedModel([], close_failure=False), max_turns=5
    )
    admission = ConsolidationDispatchAdmission(
        host.principal, host.execution_repository, host.context_port, _never_stop
    )
    await admission.admit()
    context = admission.context(
        provider="openai", integration_id="synthetic", model="gpt-4o"
    )
    assert context.session_id == host.principal.owner.session_id
    assert context.run_id == host.principal.run_id
    assert context.check_stop is not None
    assert not await context.check_stop()
    await admission.settle(
        TokenUsagePayload(prompt_tokens=20, completion_tokens=5, total_tokens=25)
    )
    assert admission.settled
    rows = await _stored_events(rdb_session_manager, host.principal)
    assert any(row.payload.get("usage") is not None for row in rows)
    with pytest.raises(RuntimeError, match="already been settled"):
        await admission.settle(None)
    with pytest.raises(RuntimeError, match="already been settled"):
        await admission.admit()


async def test_dispatch_owner_loss_refuses_external_admission(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    host = await _host(
        rdb_session_manager, _ScriptedModel([], close_failure=False), max_turns=5
    )
    async with rdb_session_manager() as session:
        await SessionExecutionRecordRepository().claim_owner_generation(
            session, host.principal.owner.session_id
        )
    admission = ConsolidationDispatchAdmission(
        host.principal, host.execution_repository, host.context_port, _never_stop
    )
    with pytest.raises(MemoryExecutionAuthorityError):
        await admission.admit()
    assert not admission.settled


async def test_dispatch_observes_common_stop_callback_before_provider_work(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    host = await _host(
        rdb_session_manager, _ScriptedModel([], close_failure=False), max_turns=5
    )

    async def stopped() -> bool:
        return True

    admission = ConsolidationDispatchAdmission(
        host.principal, host.execution_repository, host.context_port, stopped
    )
    with pytest.raises(asyncio.CancelledError):
        await admission.admit()
    assert not admission.settled
