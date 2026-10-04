"""Real PostgreSQL Lightweight operation selection, routing and settlement."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.core.model_operation import (
    ModelOperationCandidateOutcomeStatus,
    ModelOperationChainExhaustedError,
    ModelOperationKind,
    ModelOperationSnapshot,
)
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
    ModelProviderFailureRetryability,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.historical_memory_consolidation import RDBConsolidationAttempt
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
    consolidation_job_session,
    require_commit_owner,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.operations import (
    ConsolidationModelOperationRepository,
    finish_consolidation_model_operation,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import ModelCandidateIdentity
from azents.testing.consolidation import seed_consolidation_corpus
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


async def _principal(
    manager: SessionManager[AsyncSession],
) -> ConsolidationJobPrincipal:
    corpus = await seed_consolidation_corpus(manager)
    async with manager() as session:
        agent = await session.get(RDBAgent, corpus.team.agent_id)
        assert agent is not None
        integration = RDBLLMProviderIntegration(
            workspace_id=corpus.team.workspace_id,
            provider=LLMProvider.OPENAI,
            name="Synthetic internal route",
            encrypted_credentials="synthetic-unused",
            config=None,
        )
        session.add(integration)
        await session.flush()
        main = make_test_model_selection_dict(model_identifier="main-not-permitted")
        primary = make_test_model_selection_dict(
            integration_id=integration.id, model_identifier="lightweight-first"
        )
        fallback = make_test_model_selection_dict(
            integration_id=integration.id, model_identifier="lightweight-second"
        )
        options = make_test_selectable_model_option_dicts(
            model_selection=main, lightweight_model_selection=primary
        )
        second = make_test_selectable_model_option_dicts(
            model_selection=main, lightweight_model_selection=fallback
        )[1]
        candidates = options[1]["candidates"]
        fallback_candidates = second["candidates"]
        assert isinstance(candidates, list) and isinstance(fallback_candidates, list)
        options[1]["candidates"] = [*candidates, *fallback_candidates]
        agent.model_selection = main
        agent.lightweight_model_selection = primary
        agent.selectable_model_options = options
    claim = await ConsolidationOwnershipRepository(manager).claim(corpus.team)
    assert claim is not None
    await ConsolidationDraftRepository(manager).observe(
        claim.principal, path="summary.md"
    )
    return claim.principal


def _repository(
    manager: SessionManager[AsyncSession],
) -> ConsolidationModelOperationRepository:
    return ConsolidationModelOperationRepository(
        manager, AgentRepository(), ModelCandidateHealthRepository(manager)
    )


def _failure(
    operation: ModelOperationSnapshot,
    category: ModelProviderFailureCategory,
    *,
    model: str | None,
) -> ModelProviderFailure:
    selection = operation.current_candidate.model_selection
    return ModelProviderFailure(
        operation="historical_memory",
        category=category,
        retryability=ModelProviderFailureRetryability.USER_ACTION_REQUIRED,
        provider_message=None,
        status_code=429,
        provider_code=None,
        provider_error_type=None,
        provider_error_param=None,
        retry_hint_seconds=None,
        provider=selection.provider.value,
        integration=selection.llm_provider_integration_id,
        model=selection.model_identifier if model is None else model,
    )


async def test_begin_freezes_only_lightweight_and_replays_without_foreground_claim(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    repository = _repository(rdb_session_manager)
    operation = await repository.begin(principal)
    assert operation.kind is ModelOperationKind.HISTORICAL_MEMORY
    assert operation.semantic_label == "lightweight"
    assert [c.model_selection.model_identifier for c in operation.candidates] == [
        "lightweight-first",
        "lightweight-second",
    ]
    assert operation.transferred_probe_claim is None
    assert operation.outcomes[0].status is ModelOperationCandidateOutcomeStatus.ACTIVE
    assert await repository.begin(principal) == operation
    async with rdb_session_manager() as session:
        attempt = await session.get(RDBConsolidationAttempt, principal.attempt_id)
        assert attempt is not None
        assert (
            ModelOperationSnapshot.model_validate(attempt.model_operation_state)
            == operation
        )


async def test_quota_only_advances_exact_route_and_persists_exhaustion(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    repository = _repository(rdb_session_manager)
    first = await repository.begin(principal)
    with pytest.raises(ConsolidationAuthorityError, match="route does not match"):
        await repository.advance_after_quota(
            principal,
            failure=_failure(
                first,
                ModelProviderFailureCategory.QUOTA_OR_BILLING,
                model="forged-route",
            ),
        )
    assert await repository.begin(principal) == first
    second = await repository.advance_after_quota(
        principal,
        failure=_failure(
            first, ModelProviderFailureCategory.QUOTA_OR_BILLING, model=None
        ),
    )
    assert second is not None and second.cursor == 1
    assert (
        second.outcomes[0].status
        is ModelOperationCandidateOutcomeStatus.QUOTA_OR_BILLING
    )
    assert (
        await repository.advance_after_quota(
            principal,
            failure=_failure(
                second, ModelProviderFailureCategory.QUOTA_OR_BILLING, model=None
            ),
        )
        is None
    )
    async with rdb_session_manager() as session:
        attempt = await session.get(RDBConsolidationAttempt, principal.attempt_id)
        assert attempt is not None
        exhausted = ModelOperationSnapshot.model_validate(attempt.model_operation_state)
        assert exhausted.terminal_reason is not None
        assert all(
            o.status is ModelOperationCandidateOutcomeStatus.QUOTA_OR_BILLING
            for o in exhausted.outcomes
        )


@pytest.mark.parametrize(
    "category",
    [
        ModelProviderFailureCategory.RATE_LIMIT,
        ModelProviderFailureCategory.AUTHENTICATION,
        ModelProviderFailureCategory.TRANSPORT,
    ],
)
async def test_nonquota_cannot_advance_or_change_health(
    rdb_session_manager: SessionManager[AsyncSession],
    category: ModelProviderFailureCategory,
) -> None:
    principal = await _principal(rdb_session_manager)
    repository = _repository(rdb_session_manager)
    operation = await repository.begin(principal)
    with pytest.raises(ValueError, match="Only provider quota"):
        await repository.advance_after_quota(
            principal, failure=_failure(operation, category, model=None)
        )
    assert await repository.begin(principal) == operation


async def test_unavailable_chain_is_durably_exhausted_without_background_probe(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    health = ModelCandidateHealthRepository(rdb_session_manager)
    async with rdb_session_manager() as session:
        agent = await session.get(RDBAgent, principal.unit.agent_id)
        assert agent is not None
        integration_id = agent.lightweight_model_selection[
            "llm_provider_integration_id"
        ]
        assert isinstance(integration_id, str)
    for model in ("lightweight-first", "lightweight-second"):
        await health.renew_quota(
            ModelCandidateIdentity(
                workspace_id=principal.unit.workspace_id,
                llm_provider_integration_id=integration_id,
                model_identifier=model,
            )
        )
    with pytest.raises(ModelOperationChainExhaustedError):
        await _repository(rdb_session_manager).begin(principal)
    async with rdb_session_manager() as session:
        attempt = await session.get(RDBConsolidationAttempt, principal.attempt_id)
        assert attempt is not None
        operation = ModelOperationSnapshot.model_validate(attempt.model_operation_state)
        assert operation.terminal_reason is not None
        assert all(
            o.status is ModelOperationCandidateOutcomeStatus.COOLDOWN
            for o in operation.outcomes
        )
        assert operation.transferred_probe_claim is None


async def test_success_settles_operation_inside_owner_fenced_database_boundary(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    repository = _repository(rdb_session_manager)
    operation = await repository.begin(principal)
    async with consolidation_job_session(rdb_session_manager, principal) as job:
        await finish_consolidation_model_operation(
            job.session, owner=job.owner, health_repository=repository.health_repository
        )
        await require_commit_owner(job.session, job.owner)
    async with rdb_session_manager() as session:
        attempt = await session.get(RDBConsolidationAttempt, principal.attempt_id)
        assert attempt is not None
        settled = ModelOperationSnapshot.model_validate(attempt.model_operation_state)
        assert settled.operation_id == operation.operation_id
        assert (
            settled.outcomes[0].status is ModelOperationCandidateOutcomeStatus.SUCCEEDED
        )
