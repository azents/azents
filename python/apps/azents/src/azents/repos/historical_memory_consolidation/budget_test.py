"""Real PostgreSQL counted dispatches, unknown usage and hard attempt boundaries."""

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from azents.core.historical_memory_budget import (
    ConsolidationBudgetExceeded,
    ConsolidationUsage,
)
from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationModelDispatch,
)
from azents.rdb.session import SessionManager
from azents.repos.historical_memory_consolidation.budget import (
    ConsolidationBudgetRepository,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftConflict,
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.testing.consolidation import seed_consolidation_corpus


async def _principal(
    manager: SessionManager[AsyncSession],
) -> ConsolidationJobPrincipal:
    corpus = await seed_consolidation_corpus(manager)
    claim = await ConsolidationOwnershipRepository(manager).claim(corpus.team)
    assert claim is not None
    await ConsolidationDraftRepository(manager).observe(
        claim.principal, path="summary.md"
    )
    return claim.principal


def _usage(prompt: int, completion: int) -> ConsolidationUsage:
    return ConsolidationUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        cached_tokens=None,
        cache_creation_tokens=None,
        reasoning_tokens=None,
        cost_usd=None,
        cost_method=None,
        cost_source_key=None,
        cost_collected_at=None,
        cost_source_model_key=None,
        cost_estimator_version=None,
    )


async def test_physical_reservations_and_usage_replay_are_fenced_and_idempotent(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    budgets = ConsolidationBudgetRepository(rdb_session_manager)
    nonce = uuid7().hex
    first = await budgets.reserve_model(
        principal, dispatch_id=nonce, input_tokens=100, output_tokens=1000
    )
    assert first.request_number == 1
    assert (
        await budgets.reserve_model(
            principal, dispatch_id=nonce, input_tokens=100, output_tokens=1000
        )
        == first
    )
    with pytest.raises(ConsolidationDraftConflict):
        await budgets.reserve_model(
            principal, dispatch_id=nonce, input_tokens=101, output_tokens=1000
        )
    assert not await budgets.record_usage(
        principal, dispatch_id=nonce, usage=_usage(120, 25)
    )
    assert not await budgets.record_usage(
        principal, dispatch_id=nonce, usage=_usage(120, 25)
    )
    with pytest.raises(ConsolidationDraftConflict):
        await budgets.record_usage(principal, dispatch_id=nonce, usage=_usage(121, 25))
    remaining = await budgets.remaining(principal)
    assert remaining.model_requests == 31 and remaining.output_tokens == 15975
    assert remaining.input_tokens == 249880
    async with rdb_session_manager() as session:
        row = await session.get(
            RDBConsolidationModelDispatch, (principal.attempt_id, nonce)
        )
        assert row is not None and row.usage_recorded and row.usage_json is not None
        assert row.usage_json["cost_usd"] is None
        assert "raw" not in row.usage_json and "raw_hidden_params" not in row.usage_json


async def test_missing_usage_is_unknown_and_does_not_release_a_fabricated_zero(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    budgets = ConsolidationBudgetRepository(rdb_session_manager)
    nonce = uuid7().hex
    await budgets.reserve_model(
        principal, dispatch_id=nonce, input_tokens=100, output_tokens=16000
    )
    assert not await budgets.record_usage(principal, dispatch_id=nonce, usage=None)
    assert (await budgets.remaining(principal)).output_tokens == 0
    with pytest.raises(ConsolidationBudgetExceeded):
        await budgets.reserve_model(
            principal, dispatch_id=uuid7().hex, input_tokens=1, output_tokens=1
        )
    async with rdb_session_manager() as session:
        row = await session.get(
            RDBConsolidationModelDispatch, (principal.attempt_id, nonce)
        )
        assert row is not None and row.usage_recorded and row.usage_json is None


async def test_actual_over_budget_is_committed_and_blocks_later_admission(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    budgets = ConsolidationBudgetRepository(rdb_session_manager)
    nonce = uuid7().hex
    await budgets.reserve_model(
        principal, dispatch_id=nonce, input_tokens=1, output_tokens=1
    )
    assert await budgets.record_usage(
        principal, dispatch_id=nonce, usage=_usage(250001, 16001)
    )
    async with rdb_session_manager() as session:
        attempt = await session.get(RDBConsolidationAttempt, principal.attempt_id)
        assert attempt is not None
        assert attempt.input_tokens == 250001 and attempt.output_tokens == 16001
        assert attempt.failure_code == "token_budget_exceeded"
    with pytest.raises(ConsolidationBudgetExceeded):
        await budgets.remaining(principal)
    with pytest.raises(ConsolidationBudgetExceeded):
        await budgets.reserve_tools(principal, count=1)
    with pytest.raises(ConsolidationBudgetExceeded):
        await budgets.reserve_model(
            principal, dispatch_id=uuid7().hex, input_tokens=1, output_tokens=1
        )


async def test_each_transport_attempt_counts_and_tool_batch_cannot_cross_cap(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    budgets = ConsolidationBudgetRepository(rdb_session_manager)
    for index in range(32):
        nonce = uuid7().hex
        result = await budgets.reserve_model(
            principal, dispatch_id=nonce, input_tokens=1, output_tokens=1
        )
        assert result.request_number == index + 1
        assert not await budgets.record_usage(
            principal, dispatch_id=nonce, usage=_usage(1, 0)
        )
    with pytest.raises(ConsolidationBudgetExceeded):
        await budgets.reserve_model(
            principal, dispatch_id=uuid7().hex, input_tokens=1, output_tokens=1
        )
    await budgets.reserve_tools(principal, count=95)
    with pytest.raises(ConsolidationBudgetExceeded):
        await budgets.reserve_tools(principal, count=2)
    assert (await budgets.remaining(principal)).tool_calls == 1
    await budgets.reserve_tools(principal, count=1)
    async with rdb_session_manager() as session:
        count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBConsolidationModelDispatch)
            .where(RDBConsolidationModelDispatch.attempt_id == principal.attempt_id)
        )
        assert count == 32
        attempt = await session.get(RDBConsolidationAttempt, principal.attempt_id)
        assert (
            attempt is not None
            and attempt.model_requests == 32
            and attempt.tool_calls == 96
        )
