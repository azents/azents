"""Real PostgreSQL Lightweight operation selection, routing and settlement."""

import json
from unittest.mock import AsyncMock

import pytest

from azents.core.active_model_capabilities import (
    CapturedStoredChoice,
    ConfiguredModelIdentity,
)
from azents.core.enums import LLMProvider
from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.core.model_catalog_identity import catalog_source_keys
from azents.core.model_catalog_source import decode_catalog_source
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
from azents.rdb.session_capabilities import WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs
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
from azents.testing.consolidation import (
    consolidation_deadline,
    seed_consolidation_corpus,
)
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


async def _principal(
    manager: SessionManager[WriteSession],
) -> ConsolidationJobPrincipal:
    corpus = await seed_consolidation_corpus(manager)
    async with manager() as session:
        agent = await session.write_session.get(RDBAgent, corpus.team.agent_id)
        assert agent is not None
        integration = RDBLLMProviderIntegration(
            workspace_id=corpus.team.workspace_id,
            provider=LLMProvider.OPENAI,
            name="Synthetic internal route",
            encrypted_credentials="synthetic-unused",
            config=None,
        )
        session.write_session.add(integration)
        await session.write_session.flush()
        main = make_test_model_selection_dict(model_identifier="main-not-permitted")
        primary = make_test_model_selection_dict(
            integration_id=integration.id, model_identifier="lightweight-first"
        )
        fallback = make_test_model_selection_dict(
            integration_id=integration.id, model_identifier="lightweight-second"
        )
        primary["normalized_capabilities"] = _legacy_v2_capabilities()
        fallback["normalized_capabilities"] = _legacy_v2_capabilities()
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
    claim = await ConsolidationOwnershipRepository(manager).claim(
        corpus.team, deadline=consolidation_deadline()
    )
    assert claim is not None
    await ConsolidationDraftRepository(manager).observe(
        claim.principal, path="summary.md"
    )
    return claim.principal


def _repository(
    manager: SessionManager[WriteSession],
) -> ConsolidationModelOperationRepository:
    return ConsolidationModelOperationRepository(
        manager,
        AgentRepository(),
        ModelCandidateHealthRepository(manager),
        _active_metadata_repository(structured_output=True),
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
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    active_metadata = _active_metadata_repository(structured_output=True)
    repository = ConsolidationModelOperationRepository(
        rdb_session_manager,
        AgentRepository(),
        ModelCandidateHealthRepository(rdb_session_manager),
        active_metadata,
    )
    operation = await repository.begin(principal)
    assert operation.kind is ModelOperationKind.HISTORICAL_MEMORY
    assert operation.semantic_label == "lightweight"
    assert [c.model_selection.model_identifier for c in operation.candidates] == [
        "lightweight-first",
        "lightweight-second",
    ]
    assert operation.transferred_probe_claim is None
    assert operation.outcomes[0].status is ModelOperationCandidateOutcomeStatus.ACTIVE
    assert all(
        candidate.model_selection.normalized_capabilities.tool_calling.supported
        for candidate in operation.candidates
    )
    active_metadata.capture_exact_choices_in_session.assert_awaited_once()
    active_metadata.inputs_match_in_session.assert_awaited_once()
    active_metadata.reset_mock()
    active_metadata.capture_exact_choices_in_session.side_effect = AssertionError(
        "Frozen consolidation must not query active metadata."
    )
    assert await repository.begin(principal) == operation
    active_metadata.capture_exact_choices_in_session.assert_not_awaited()
    active_metadata.inputs_match_in_session.assert_not_awaited()
    async with rdb_session_manager() as session:
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, principal.attempt_id
        )
        assert attempt is not None
        assert (
            ModelOperationSnapshot.model_validate(attempt.model_operation_state)
            == operation
        )
        persisted_agent = await AgentRepository().get_by_id(
            session, principal.unit.agent_id
        )
        assert persisted_agent is not None
        persisted_row = await session.read_session.get(
            RDBAgent, principal.unit.agent_id
        )
        assert persisted_row is not None
        assert (
            persisted_row.lightweight_model_selection["normalized_capabilities"][
                "semantic_contract"
            ]["version"]
            == 2
        )
        assert all(
            not candidate.model_selection.normalized_capabilities.tool_calling.supported
            for option in persisted_agent.selectable_model_options
            for candidate in option.candidates
        )


async def test_begin_metadata_drift_does_not_persist_a_new_operation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """The existing consolidation owner fence precedes execution-state writes."""
    principal = await _principal(rdb_session_manager)
    active_metadata = _active_metadata_repository(structured_output=True)
    active_metadata.inputs_match_in_session.return_value = False
    repository = ConsolidationModelOperationRepository(
        rdb_session_manager,
        AgentRepository(),
        ModelCandidateHealthRepository(rdb_session_manager),
        active_metadata,
    )
    with pytest.raises(ConsolidationAuthorityError, match="metadata changed"):
        await repository.begin(principal)
    async with rdb_session_manager() as session:
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, principal.attempt_id
        )
        assert attempt is not None
        assert attempt.model_operation_state is None


async def test_quota_only_advances_exact_route_and_persists_exhaustion(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    active_metadata = _active_metadata_repository(structured_output=True)
    repository = ConsolidationModelOperationRepository(
        rdb_session_manager,
        AgentRepository(),
        ModelCandidateHealthRepository(rdb_session_manager),
        active_metadata,
    )
    first = await repository.begin(principal)
    active_metadata.reset_mock()
    active_metadata.capture_exact_choices_in_session.side_effect = AssertionError(
        "Quota/reuse must retain the frozen chain without active metadata."
    )
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
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, principal.attempt_id
        )
        assert attempt is not None
        exhausted = ModelOperationSnapshot.model_validate(attempt.model_operation_state)
        assert exhausted.terminal_reason is not None
        assert all(
            o.status is ModelOperationCandidateOutcomeStatus.QUOTA_OR_BILLING
            for o in exhausted.outcomes
        )
    active_metadata.capture_exact_choices_in_session.assert_not_awaited()
    active_metadata.inputs_match_in_session.assert_not_awaited()


@pytest.mark.parametrize(
    "category",
    [
        ModelProviderFailureCategory.RATE_LIMIT,
        ModelProviderFailureCategory.AUTHENTICATION,
        ModelProviderFailureCategory.TRANSPORT,
    ],
)
async def test_nonquota_cannot_advance_or_change_health(
    rdb_session_manager: SessionManager[WriteSession],
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
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    health = ModelCandidateHealthRepository(rdb_session_manager)
    async with rdb_session_manager() as session:
        agent = await session.read_session.get(RDBAgent, principal.unit.agent_id)
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
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, principal.attempt_id
        )
        assert attempt is not None
        operation = ModelOperationSnapshot.model_validate(attempt.model_operation_state)
        assert operation.terminal_reason is not None
        assert all(
            o.status is ModelOperationCandidateOutcomeStatus.COOLDOWN
            for o in operation.outcomes
        )
        assert operation.transferred_probe_claim is None


async def test_success_settles_operation_inside_owner_fenced_database_boundary(
    rdb_session_manager: SessionManager[WriteSession],
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
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, principal.attempt_id
        )
        assert attempt is not None
        settled = ModelOperationSnapshot.model_validate(attempt.model_operation_state)
        assert settled.operation_id == operation.operation_id
        assert (
            settled.outcomes[0].status is ModelOperationCandidateOutcomeStatus.SUCCEEDED
        )


def _active_metadata_repository(*, structured_output: bool) -> AsyncMock:
    """Capture synthetic exact declarations, never the saved capability object."""
    repository = AsyncMock(spec=ActiveModelCapabilitiesRepository)

    async def capture(
        session: WriteSession,
        *,
        workspace_id: str,
        identities: tuple[ConfiguredModelIdentity, ...],
    ) -> CapturedActiveChoiceInputs:
        del session
        choices = []
        for identity in identities:
            key = catalog_source_keys(
                provider=identity.provider, model_identifier=identity.model_identifier
            )[0]
            source = decode_catalog_source(
                json.dumps(
                    {
                        key.source_model_key: {
                            "litellm_provider": key.provider,
                            "mode": "chat",
                            "supported_endpoints": ["/v1/responses"],
                            "supported_modalities": ["text"],
                            "supported_output_modalities": ["text"],
                            "supports_function_calling": True,
                            "supports_response_schema": structured_output,
                            "max_input_tokens": 128000,
                            "max_output_tokens": 16384,
                        }
                    }
                ).encode()
            ).models[0]
            choices.append(
                CapturedStoredChoice(
                    identity=identity,
                    source_metadata=None,
                    source_models=(source,),
                    supported_execution_options=(),
                    model_developer=None,
                    catalog_id="synthetic-local-catalog",
                )
            )
        return CapturedActiveChoiceInputs(
            workspace_id=workspace_id,
            choices=tuple(choices),
            catalog_choices=(),
            source_metadata=None,
            source_expectations=(),
        )

    repository.capture_exact_choices_in_session.side_effect = capture
    repository.inputs_match_in_session.return_value = True
    return repository


def _legacy_v2_capabilities() -> dict[str, object]:
    """Keep a real persisted v2 declaration unknown until exact facts compile it."""
    unknown = {"state": "unknown", "origin": None, "predicate": None}
    return {
        "semantic_contract": {
            "version": 2,
            "reasoning": {
                "support": unknown,
                "completeness": "unknown",
                "efforts": [],
                "default_effort": None,
            },
            "reasoning_summaries": unknown,
            "function_calling": unknown,
            "parallel_function_calls": unknown,
            "strict_function_schema": unknown,
            "structured_response": unknown,
            "parameters": {
                name: unknown
                for name in (
                    "temperature",
                    "max_output_tokens",
                    "top_p",
                    "top_k",
                    "stop_sequences",
                )
            },
            "input_modalities": [],
            "output_modalities": [],
            "built_in_tools": [],
        }
    }
