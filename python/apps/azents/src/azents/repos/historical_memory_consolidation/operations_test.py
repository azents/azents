"""Configured Lightweight candidates and quota-only progression on common Runs."""

import json
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from azents.core.active_model_capabilities import (
    CapturedStoredChoice,
    ConfiguredModelIdentity,
)
from azents.core.enums import AgentRunStatus, LLMProvider
from azents.core.historical_memory_consolidation import (
    MemoryExecutionAuthorityError,
    MemoryExecutionPrincipal,
)
from azents.core.model_catalog_identity import catalog_source_keys
from azents.core.model_catalog_source import decode_catalog_source
from azents.core.model_operation import (
    ModelOperationCandidateOutcomeStatus,
    ModelOperationKind,
    ModelOperationSnapshot,
    ModelOperationState,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
    ModelProviderFailureRetryability,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.session_execution_file import RDBSessionExecutionFile
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.historical_memory_consolidation.operations import (
    ConsolidationModelOperationRepository,
)
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.services.historical_memory.consolidation_host_test import (
    _host,
    _ScriptedModel,
)
from azents.testing.consolidation import memory_execution_repository
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


def _metadata() -> AsyncMock:
    repository = AsyncMock(spec=ActiveModelCapabilitiesRepository)

    async def capture(
        session: WriteSession,
        *,
        workspace_id: str,
        identities: tuple[ConfiguredModelIdentity, ...],
    ) -> CapturedActiveChoiceInputs:
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
                            "supports_response_schema": True,
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
                    catalog_id="synthetic-current-catalog",
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


async def _principal(manager: SessionManager[WriteSession]) -> MemoryExecutionPrincipal:
    host = await _host(manager, _ScriptedModel([], close_failure=False), max_turns=5)
    async with manager() as session:
        agent = await session.write_session.get(
            RDBAgent, host.principal.binding.unit.agent_id
        )
        assert agent is not None
        integration = RDBLLMProviderIntegration(
            workspace_id=agent.workspace_id,
            provider=LLMProvider.OPENAI,
            name="Synthetic common Memory route",
            encrypted_credentials="unused",
            config=None,
        )
        session.write_session.add(integration)
        await session.write_session.flush()
        main = make_test_model_selection_dict(
            integration_id=integration.id, model_identifier="main-not-permitted"
        )
        first = make_test_model_selection_dict(
            integration_id=integration.id, model_identifier="lightweight-first"
        )
        second = make_test_model_selection_dict(
            integration_id=integration.id, model_identifier="lightweight-second"
        )
        options = make_test_selectable_model_option_dicts(
            model_selection=main, lightweight_model_selection=first
        )
        other = make_test_selectable_model_option_dicts(
            model_selection=main, lightweight_model_selection=second
        )
        candidates = options[1]["candidates"]
        other_candidates = other[1]["candidates"]
        assert isinstance(candidates, list) and isinstance(other_candidates, list)
        options[1]["candidates"] = [*candidates, *other_candidates]
        agent.model_selection = main
        agent.lightweight_model_selection = first
        agent.selectable_model_options = options
    return host.principal


def _repository(
    manager: SessionManager[WriteSession], metadata: AsyncMock
) -> ConsolidationModelOperationRepository:
    return ConsolidationModelOperationRepository(
        manager,
        AgentRepository(),
        ModelCandidateHealthRepository(manager),
        metadata,
        memory_execution_repository(manager),
        AgentRunRepository(),
    )


def _failure(
    operation: ModelOperationSnapshot,
    category: ModelProviderFailureCategory,
    *,
    model: str | None,
) -> ModelProviderFailure:
    selected = operation.current_candidate.model_selection
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
        provider=selected.provider.value,
        integration=selected.llm_provider_integration_id,
        model=selected.model_identifier if model is None else model,
    )


async def test_memory_uses_lightweight_and_freezes_common_run_snapshot(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    metadata = _metadata()
    repository = _repository(rdb_session_manager, metadata)
    operation = await repository.begin(principal)
    assert operation.kind is ModelOperationKind.FOREGROUND
    assert (
        operation.current_candidate.model_selection.model_identifier
        == "lightweight-first"
    )
    assert operation.semantic_label == "lightweight"
    metadata.capture_exact_choices_in_session.assert_awaited_once()
    metadata.reset_mock()
    metadata.capture_exact_choices_in_session.side_effect = AssertionError(
        "Frozen route must not recapture metadata"
    )
    assert await repository.begin(principal) == operation
    async with rdb_session_manager() as session:
        run = await session.read_session.get(RDBAgentRun, principal.run_id)
        assert run is not None and run.model_operation_state is not None
        assert (
            ModelOperationState.model_validate(run.model_operation_state).foreground
            == operation
        )
        assert run.session_id == principal.owner.session_id
    metadata.capture_exact_choices_in_session.assert_not_awaited()


async def test_metadata_drift_rolls_back_common_run_model_operation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    metadata = _metadata()
    metadata.inputs_match_in_session.return_value = False
    with pytest.raises(MemoryExecutionAuthorityError, match="metadata changed"):
        await _repository(rdb_session_manager, metadata).begin(principal)
    async with rdb_session_manager() as session:
        run = await session.read_session.get(RDBAgentRun, principal.run_id)
        assert run is not None and run.model_operation_state is None


async def test_quota_replaces_host_with_exact_captured_route_without_main_fallback(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    principal = await _principal(rdb_session_manager)
    metadata = _metadata()
    repository = _repository(rdb_session_manager, metadata)
    executions = memory_execution_repository(rdb_session_manager)
    first = await repository.begin(principal)
    await executions.start_turn(principal)
    with pytest.raises(MemoryExecutionAuthorityError, match="route does not match"):
        await repository.replace_after_quota(
            principal,
            failure=_failure(
                first, ModelProviderFailureCategory.QUOTA_OR_BILLING, model="forged"
            ),
        )
    replacement = await repository.replace_after_quota(
        principal,
        failure=_failure(
            first, ModelProviderFailureCategory.QUOTA_OR_BILLING, model=None
        ),
    )
    assert replacement is not None
    assert replacement.session_id != principal.owner.session_id
    assert replacement.deadline_at == principal.binding.deadline_at
    assert replacement.execution_policy == principal.binding.execution_policy
    assert replacement.started_turns == 1
    async with rdb_session_manager() as session:
        old = await session.read_session.get(RDBAgentRun, principal.run_id)
        assert old is not None and old.status is AgentRunStatus.FAILED
        assert not list(
            await session.read_session.scalars(
                sa.select(RDBSessionExecutionFile).where(
                    RDBSessionExecutionFile.session_id == replacement.session_id
                )
            )
        )
        assert not list(
            await session.read_session.scalars(
                sa.select(RDBEvent).where(RDBEvent.session_id == replacement.session_id)
            )
        )
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, replacement.session_id
        )
    owner = SessionExecutionOwner(replacement.session_id, generation)
    assert await executions.recover_worker_execution(replacement, owner) == replacement
    second_principal = await executions.open_run(replacement, owner)
    metadata.capture_exact_choices_in_session.side_effect = AssertionError(
        "Frozen route changed"
    )
    second = await repository.begin(second_principal)
    assert second.operation_id == first.operation_id
    assert second.cursor == 1
    assert (
        second.current_candidate.model_selection.model_identifier
        == "lightweight-second"
    )
    assert (
        second.outcomes[0].status
        is ModelOperationCandidateOutcomeStatus.QUOTA_OR_BILLING
    )
    await executions.start_turn(second_principal)
    assert (
        await repository.replace_after_quota(
            second_principal,
            failure=_failure(
                second, ModelProviderFailureCategory.QUOTA_OR_BILLING, model=None
            ),
        )
        is None
    )
    async with rdb_session_manager() as session:
        run = await session.read_session.get(RDBAgentRun, second_principal.run_id)
        assert run is not None and run.status is AgentRunStatus.FAILED
        assert run.model_operation_state is not None
        exhausted = ModelOperationState.model_validate(
            run.model_operation_state
        ).foreground
        assert exhausted is not None and exhausted.terminal_reason is not None
        assert all(
            outcome.status is ModelOperationCandidateOutcomeStatus.QUOTA_OR_BILLING
            for outcome in exhausted.outcomes
        )


@pytest.mark.parametrize(
    "category",
    [
        ModelProviderFailureCategory.RATE_LIMIT,
        ModelProviderFailureCategory.AUTHENTICATION,
        ModelProviderFailureCategory.TRANSPORT,
    ],
)
async def test_nonquota_error_cannot_advance_the_memory_chain(
    rdb_session_manager: SessionManager[WriteSession],
    category: ModelProviderFailureCategory,
) -> None:
    principal = await _principal(rdb_session_manager)
    repository = _repository(rdb_session_manager, _metadata())
    first = await repository.begin(principal)
    with pytest.raises(ValueError, match="Only provider quota"):
        await repository.replace_after_quota(
            principal, failure=_failure(first, category, model=None)
        )
    assert await repository.begin(principal) == first
