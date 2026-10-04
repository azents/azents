"""Physical request journals observe dispatches without memory-only cutoffs."""

import datetime
from typing import Literal

import httpx2
import pytest

from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.engine.events.types import ModelCostProvenance, TokenUsagePayload
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
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.budget import (
    ConsolidationExecutionRepository,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.services.historical_memory.consolidation_dispatch import (
    ConsolidationDispatchAdmission,
    scalar_consolidation_usage,
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


def _usage() -> TokenUsagePayload:
    return TokenUsagePayload(
        prompt_tokens=20,
        completion_tokens=5,
        total_tokens=25,
        raw={"sensitive": "not-persisted"},
    )


@pytest.mark.parametrize("method", ["provider_reported", "estimated"])
def test_scalar_usage_retains_current_pricing_provenance_without_raw_payloads(
    method: Literal["provider_reported", "estimated"],
) -> None:
    collected = datetime.datetime(2026, 10, 4, tzinfo=datetime.UTC)
    usage = _usage().model_copy(
        update={
            "cost_usd": 0.01,
            "cost_provenance": ModelCostProvenance(
                method=method,
                provider="openai",
                model_identifier="exact-selected-model",
                service_tier=None,
                source_key="synthetic_current_source",
                source_model_key="openai/exact-selected-model",
                collected_at=collected,
                estimator_version="1",
            ),
        }
    )
    scalar = scalar_consolidation_usage(usage)
    assert scalar is not None
    assert scalar.cost_method == method
    assert scalar.cost_source_key == "synthetic_current_source"
    assert scalar.cost_collected_at == collected
    assert scalar.cost_source_model_key == "openai/exact-selected-model"
    assert scalar.cost_estimator_version == "1"
    assert scalar.cost_usd == 0.01
    assert "sensitive" not in scalar.model_dump_json()
    assert scalar_consolidation_usage(None) is None


def _unexpected_mapper(
    error: Exception, *, call_context: ModelStreamCallContext
) -> ModelProviderFailure:
    raise AssertionError("No provider failure is expected.")


async def test_http_proxy_journal_sees_committed_reservation_before_every_send(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    repository = ConsolidationExecutionRepository(rdb_session_manager)
    admission = ConsolidationDispatchAdmission(principal, repository, 100, 100)
    journal: list[int] = []

    async def proxy(request: httpx2.Request) -> httpx2.Response:
        async with rdb_session_manager() as session:
            attempt = await session.read_session.get(
                RDBConsolidationAttempt, principal.attempt_id
            )
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
    async with rdb_session_manager() as session:
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, principal.attempt_id
        )
        assert attempt is not None
        assert attempt.input_tokens == 20 and attempt.output_tokens == 5
    for index, reservation in enumerate(admission.reservations):
        async with rdb_session_manager() as session:
            row = await session.read_session.get(
                RDBConsolidationModelDispatch,
                (principal.attempt_id, reservation.dispatch_id),
            )
            assert row is not None and row.usage_recorded
            if index == 0:
                assert row.usage_json is None
            else:
                assert row.usage_json is not None and "raw" not in row.usage_json
                assert "sensitive" not in str(row.usage_json)


async def test_physical_retry_has_no_memory_only_output_budget(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    repository = ConsolidationExecutionRepository(rdb_session_manager)
    admission = ConsolidationDispatchAdmission(principal, repository, 1, None)
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
        await client.post("https://synthetic.invalid/responses")
    assert sent
    await admission.settle(None)
    assert len(admission.reservations) == 2
    assert all(item.output_tokens is None for item in admission.reservations)
    with pytest.raises(ModelDispatchAdmissionError, match="admission"):
        await admission.admit()


async def test_large_actual_usage_is_durable_without_refusing_completion(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    repository = ConsolidationExecutionRepository(rdb_session_manager)
    admission = ConsolidationDispatchAdmission(principal, repository, 1, 1)
    await admission.admit()
    await admission.settle(
        TokenUsagePayload(
            prompt_tokens=250001,
            completion_tokens=16001,
            total_tokens=266002,
            raw={},
        )
    )
    assert admission.settled
    async with rdb_session_manager() as session:
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, principal.attempt_id
        )
        assert attempt is not None
        assert attempt.input_tokens == 250001 and attempt.output_tokens == 16001
    await repository.authorize(principal)
