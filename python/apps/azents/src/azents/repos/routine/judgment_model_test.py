"""Judge labels resolve current local evidence and common background fallback."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.active_model_capabilities import (
    CapturedStoredChoice,
    ConfiguredModelIdentity,
)
from azents.core.agent import SelectableModelCandidate, SelectableModelOption
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.model_operation import ModelOperationCandidateOutcomeStatus
from azents.core.routine import RoutineScope
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs
from azents.repos.agent import AgentRepository
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import (
    ModelCandidateHealthObservation,
    ModelCandidateHealthStatus,
)
from azents.repos.routine.judgment_model import RoutineJudgmentModelRepository
from azents.testing.model_metadata import make_test_source_payload
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)
from azents.worker.run.executor_test import _default_agent

_NOW = datetime.datetime(2026, 10, 21, tzinfo=datetime.UTC)


class JudgmentModelFixture(NamedTuple):
    repository: RoutineJudgmentModelRepository
    agents: AsyncMock
    metadata: AsyncMock
    health: AsyncMock
    scope: RoutineScope
    owner: SessionExecutionOwner
    profile: RequestedInferenceProfile


def option_for(*models: str) -> SelectableModelOption:
    return SelectableModelOption(
        label="default",
        candidates=[
            SelectableModelCandidate(
                model_selection=make_test_model_selection(
                    provider=LLMProvider.XAI_OAUTH,
                    model_identifier=model,
                    integration_id="integration",
                ),
                settings=make_test_model_settings(),
            )
            for model in models
        ],
        subagent_enabled=True,
        subagent_guidance=None,
    )


def captured_for(option: SelectableModelOption) -> CapturedActiveChoiceInputs:
    sources = make_test_source_payload(
        {
            f"xai/{item.model_selection.model_identifier}": {
                "litellm_provider": "xai",
                "mode": "chat",
                "supports_response_schema": True,
                "supports_function_calling": True,
            }
            for item in option.candidates
        }
    )
    by_key = {model.source_key: model for model in sources.models}
    return CapturedActiveChoiceInputs(
        workspace_id="workspace-001",
        choices=tuple(
            CapturedStoredChoice(
                identity=ConfiguredModelIdentity.from_selection(item.model_selection),
                source_metadata={"provider_metadata": {"api_backend": "responses"}},
                source_models=(by_key[f"xai/{item.model_selection.model_identifier}"],),
                supported_execution_options=(),
                model_developer=LLMModelDeveloper.XAI,
                catalog_id="catalog",
            )
            for item in option.candidates
        ),
        catalog_choices=(),
        source_metadata=None,
        source_expectations=(),
    )


def model_fixture(
    monkeypatch: pytest.MonkeyPatch, option: SelectableModelOption
) -> JudgmentModelFixture:
    raw = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(raw)

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        yield session

    monkeypatch.setattr(
        "azents.repos.routine.judgment_model.fence_routine_scope", AsyncMock()
    )
    agents = AsyncMock(spec=AgentRepository)
    agent = _default_agent()
    agents.get_by_id.return_value = agent.model_copy(
        update={
            "selectable_model_options": [option],
            "model_selection": option.candidates[0].model_selection,
        }
    )
    metadata = AsyncMock(spec=ActiveModelCapabilitiesRepository)
    metadata.capture_exact_choices_in_session.return_value = captured_for(option)
    metadata.inputs_match_in_session.return_value = True
    health = AsyncMock(spec=ModelCandidateHealthRepository)
    available = ModelCandidateHealthObservation(
        status=ModelCandidateHealthStatus.AVAILABLE, health=None, server_time=_NOW
    )
    health.snapshot_for_background_in_session.return_value = available
    health.renew_quota_in_session.return_value = available
    return JudgmentModelFixture(
        RoutineJudgmentModelRepository(manager, agents, metadata, health),
        agents,
        metadata,
        health,
        RoutineScope(
            workspace_id=agent.workspace_id, agent_id=agent.id, session_id="session-001"
        ),
        SessionExecutionOwner(session_id="session-001", owner_generation=1),
        RequestedInferenceProfile(
            model_target_label="default",
            reasoning_effort=None,
            enabled_execution_options=[],
        ),
    )


async def test_each_judgment_resolves_label_and_current_source_without_resave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = option_for("grok-4.5")
    fixture = model_fixture(monkeypatch, first)
    initial = await fixture.repository.prepare(
        scope=fixture.scope,
        owner=fixture.owner,
        profile=fixture.profile,
        operation_id="1" * 32,
    )
    assert initial is not None
    selected = initial.operation.current_candidate.model_selection
    assert selected.normalized_capabilities.structured_response
    assert not first.candidates[
        0
    ].model_selection.normalized_capabilities.structured_response
    second = option_for("grok-4.6")
    agent = fixture.agents.get_by_id.return_value
    fixture.agents.get_by_id.return_value = agent.model_copy(
        update={"selectable_model_options": [second]}
    )
    fixture.metadata.capture_exact_choices_in_session.return_value = captured_for(
        second
    )
    updated = await fixture.repository.prepare(
        scope=fixture.scope,
        owner=fixture.owner,
        profile=fixture.profile,
        operation_id="2" * 32,
    )
    assert updated is not None
    assert (
        updated.operation.current_candidate.model_selection.model_identifier
        == "grok-4.6"
    )
    assert (
        initial.operation.current_candidate.model_selection.model_identifier
        == "grok-4.5"
    )


async def test_quota_advances_current_chain_and_updates_shared_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = model_fixture(monkeypatch, option_for("grok-4.5", "grok-4.6"))
    current = await fixture.repository.prepare(
        scope=fixture.scope,
        owner=fixture.owner,
        profile=fixture.profile,
        operation_id="1" * 32,
    )
    assert current is not None
    advanced = await fixture.repository.advance_after_quota(
        scope=fixture.scope, owner=fixture.owner, current=current
    )
    assert advanced is not None
    assert (
        advanced.operation.current_candidate.model_selection.model_identifier
        == "grok-4.6"
    )
    assert (
        advanced.operation.outcomes[0].status
        is ModelOperationCandidateOutcomeStatus.QUOTA_OR_BILLING
    )
    assert fixture.health.renew_quota_in_session.await_count == 1
    exhausted = await fixture.repository.advance_after_quota(
        scope=fixture.scope, owner=fixture.owner, current=advanced
    )
    assert exhausted is None
    assert fixture.health.renew_quota_in_session.await_count == 2


@pytest.mark.parametrize(
    "status",
    [
        ModelCandidateHealthStatus.COOLDOWN,
        ModelCandidateHealthStatus.RECOVERY_PENDING,
        ModelCandidateHealthStatus.CLAIMED,
    ],
)
async def test_judge_uses_background_health_policy(
    monkeypatch: pytest.MonkeyPatch, status: ModelCandidateHealthStatus
) -> None:
    fixture = model_fixture(monkeypatch, option_for("grok-4.5", "grok-4.6"))
    fixture.health.snapshot_for_background_in_session.side_effect = [
        ModelCandidateHealthObservation(status=status, health=None, server_time=_NOW),
        ModelCandidateHealthObservation(
            status=ModelCandidateHealthStatus.AVAILABLE, health=None, server_time=_NOW
        ),
    ]
    current = await fixture.repository.prepare(
        scope=fixture.scope,
        owner=fixture.owner,
        profile=fixture.profile,
        operation_id="1" * 32,
    )
    assert current is not None
    assert current.operation.cursor == 1
    fixture.health.claim_foreground_probe_in_session.assert_not_awaited()
