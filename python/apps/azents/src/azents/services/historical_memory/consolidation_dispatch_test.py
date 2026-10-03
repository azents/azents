"""Physical request journals observe committed internal budgets, not loop turns."""

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.historical_memory_budget import ConsolidationBudgetExceeded
from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.engine.events.types import TokenUsagePayload
from azents.engine.model_stream import (
    ModelDispatchAdmissionError,
    ModelStreamCallContext,
    ModelStreamTimeoutPolicy,
)
from azents.engine.providers.http_observation import ObservedHTTPX2Transport
from azents.engine.providers.observation_state import NativeObservationState
from azents.engine.run.provider_failure import ModelProviderFailure
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationModelDispatch,
)
from azents.rdb.session import SessionManager
from azents.repos.historical_memory_consolidation.budget import (
    ConsolidationBudgetRepository,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.services.historical_memory.consolidation_dispatch import (
    ConsolidationDispatchAdmission,
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


def _usage() -> TokenUsagePayload:
    return TokenUsagePayload(
        prompt_tokens=20,
        completion_tokens=5,
        total_tokens=25,
        raw={"sensitive": "not-persisted"},
    )


def _unexpected_mapper(
    error: Exception, *, call_context: ModelStreamCallContext
) -> ModelProviderFailure:
    raise AssertionError("No provider failure is expected.")


async def test_http_proxy_journal_sees_committed_reservation_before_every_send(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    repository = ConsolidationBudgetRepository(rdb_session_manager)
    admission = ConsolidationDispatchAdmission(principal, repository, 100, 100)
    journal: list[int] = []

    async def proxy(request: httpx2.Request) -> httpx2.Response:
        async with rdb_session_manager() as session:
            attempt = await session.get(RDBConsolidationAttempt, principal.attempt_id)
            assert attempt is not None
            journal.append(attempt.model_requests)
        return httpx2.Response(200, content=b"{}")

    # Each explicit retry uses a new adapter generation, still the same attempt.
    for _ in range(2):
        state = NativeObservationState(
            protocol="responses",
            call_context=admission.context(
                unit_id="u" * 32,
                provider="xai",
                integration_id="i" * 32,
                model="selected",
            ),
            timeout_policy=ModelStreamTimeoutPolicy(5, 5, 10),
            sdk_failure_mapper=_unexpected_mapper,
        )
        async with httpx2.AsyncClient(
            transport=ObservedHTTPX2Transport(
                delegate=httpx2.MockTransport(proxy), state=state
            )
        ) as client:
            await client.post("https://synthetic.invalid/responses")
    await admission.settle(_usage())
    assert journal == [1, 2]
    assert (await repository.remaining(principal)).input_tokens == 250000 - 100 - 20
    for index, reservation in enumerate(admission.reservations):
        async with rdb_session_manager() as session:
            row = await session.get(
                RDBConsolidationModelDispatch,
                (principal.attempt_id, reservation.dispatch_id),
            )
            assert row is not None and row.usage_recorded
            if index == 0:
                assert row.usage_json is None
            else:
                assert row.usage_json is not None and "raw" not in row.usage_json
                assert "sensitive" not in str(row.usage_json)


async def test_physical_budget_refusal_blocks_the_proxy_and_remains_nonprovider(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    repository = ConsolidationBudgetRepository(rdb_session_manager)
    admission = ConsolidationDispatchAdmission(principal, repository, 1, 16000)
    await admission.admit()
    sent = False

    def proxy(request: httpx2.Request) -> httpx2.Response:
        nonlocal sent
        sent = True
        return httpx2.Response(200, content=b"{}")

    state = NativeObservationState(
        protocol="responses",
        call_context=admission.context(
            unit_id="u" * 32, provider="xai", integration_id="i" * 32, model="selected"
        ),
        timeout_policy=ModelStreamTimeoutPolicy(5, 5, 10),
        sdk_failure_mapper=_unexpected_mapper,
    )
    async with httpx2.AsyncClient(
        transport=ObservedHTTPX2Transport(
            delegate=httpx2.MockTransport(proxy), state=state
        )
    ) as client:
        with pytest.raises(ModelDispatchAdmissionError) as error:
            await client.post("https://synthetic.invalid/responses")
    assert error.value.reason == "budget" and not sent
    await admission.settle(None)
    assert len(admission.reservations) == 1
    with pytest.raises(ModelDispatchAdmissionError, match="admission"):
        await admission.admit()


async def test_actual_usage_excess_is_durable_and_cannot_become_normal_completion(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    repository = ConsolidationBudgetRepository(rdb_session_manager)
    admission = ConsolidationDispatchAdmission(principal, repository, 1, 1)
    await admission.admit()
    with pytest.raises(ConsolidationBudgetExceeded):
        await admission.settle(
            TokenUsagePayload(
                prompt_tokens=250001,
                completion_tokens=16001,
                total_tokens=266002,
                raw={},
            )
        )
    assert admission.settled
    with pytest.raises(ConsolidationBudgetExceeded):
        await repository.remaining(principal)
