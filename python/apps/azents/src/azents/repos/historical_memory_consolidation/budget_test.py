"""Real PostgreSQL observations remain fenced without execution spend/count caps."""

import pytest
import sqlalchemy as sa
from uuid6 import uuid7

from azents.core.historical_memory_budget import ConsolidationUsage
from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationModelDispatch,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.budget import (
    ConsolidationExecutionRepository,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftConflict,
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.testing.consolidation import (
    consolidation_deadline,
    seed_consolidation_corpus,
)


async def _principal(
    manager: SessionManager[WriteSession],
) -> ConsolidationJobPrincipal:
    corpus = await seed_consolidation_corpus(manager)
    claim = await ConsolidationOwnershipRepository(manager).claim(
        corpus.team, deadline=consolidation_deadline()
    )
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


async def test_dispatch_and_usage_replay_are_fenced_and_idempotent(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    ledger = ConsolidationExecutionRepository(rdb_session_manager)
    nonce = uuid7().hex
    first = await ledger.reserve_model(
        principal, dispatch_id=nonce, input_tokens=100, output_tokens=20000
    )
    assert first.request_number == 1
    assert (
        await ledger.reserve_model(
            principal, dispatch_id=nonce, input_tokens=100, output_tokens=20000
        )
        == first
    )
    with pytest.raises(ConsolidationDraftConflict):
        await ledger.reserve_model(
            principal, dispatch_id=nonce, input_tokens=101, output_tokens=20000
        )
    await ledger.record_usage(principal, dispatch_id=nonce, usage=_usage(120, 25))
    await ledger.record_usage(principal, dispatch_id=nonce, usage=_usage(120, 25))
    with pytest.raises(ConsolidationDraftConflict):
        await ledger.record_usage(principal, dispatch_id=nonce, usage=_usage(121, 25))
    async with rdb_session_manager() as session:
        row = await session.read_session.get(
            RDBConsolidationModelDispatch, (principal.attempt_id, nonce)
        )
        assert row is not None and row.usage_recorded and row.usage_json is not None
        assert row.usage_json["cost_usd"] is None
        assert "raw" not in row.usage_json and "raw_hidden_params" not in row.usage_json
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, principal.attempt_id
        )
        assert attempt is not None and attempt.input_tokens == 120
        assert attempt.output_tokens == 25 and attempt.failure_code is None


async def test_missing_usage_and_unspecified_output_remain_explicit_and_admissible(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    ledger = ConsolidationExecutionRepository(rdb_session_manager)
    nonce = uuid7().hex
    await ledger.reserve_model(
        principal, dispatch_id=nonce, input_tokens=300000, output_tokens=None
    )
    await ledger.record_usage(principal, dispatch_id=nonce, usage=None)
    await ledger.authorize(principal)
    await ledger.reserve_model(
        principal, dispatch_id=uuid7().hex, input_tokens=1, output_tokens=None
    )
    async with rdb_session_manager() as session:
        row = await session.read_session.get(
            RDBConsolidationModelDispatch, (principal.attempt_id, nonce)
        )
        assert row is not None and row.usage_recorded and row.usage_json is None
        assert row.reserved_output_tokens is None


async def test_large_actual_totals_do_not_block_models_tools_or_publication_authority(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    ledger = ConsolidationExecutionRepository(rdb_session_manager)
    nonce = uuid7().hex
    await ledger.reserve_model(
        principal, dispatch_id=nonce, input_tokens=300000, output_tokens=64000
    )
    await ledger.record_usage(principal, dispatch_id=nonce, usage=_usage(500000, 50000))
    await ledger.authorize(principal)
    await ledger.reserve_tools(principal, count=150)
    await ledger.reserve_model(
        principal, dispatch_id=uuid7().hex, input_tokens=300000, output_tokens=None
    )
    async with rdb_session_manager() as session:
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, principal.attempt_id
        )
        assert attempt is not None
        assert attempt.input_tokens == 500000 and attempt.output_tokens == 50000
        assert attempt.failure_code is None and attempt.tool_calls == 150


async def test_physical_retries_and_tools_are_counted_without_memory_only_caps(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    ledger = ConsolidationExecutionRepository(rdb_session_manager)
    for index in range(35):
        nonce = uuid7().hex
        result = await ledger.reserve_model(
            principal, dispatch_id=nonce, input_tokens=1, output_tokens=None
        )
        assert result.request_number == index + 1
        await ledger.record_usage(principal, dispatch_id=nonce, usage=_usage(1, 0))
    await ledger.reserve_tools(principal, count=100)
    await ledger.reserve_tools(principal, count=3)
    async with rdb_session_manager() as session:
        count = await session.read_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBConsolidationModelDispatch)
            .where(RDBConsolidationModelDispatch.attempt_id == principal.attempt_id)
        )
        assert count == 35
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, principal.attempt_id
        )
        assert (
            attempt is not None
            and attempt.model_requests == 35
            and attempt.tool_calls == 103
        )
