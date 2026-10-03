"""A healthy assigned model is never skipped for incompatible request controls."""

import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import SelectableModelCandidate, SelectableModelOption
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.core.model_operation import ModelOperationKind, build_model_operation
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import (
    ForegroundProbeOutcome,
    ForegroundProbeResult,
    ModelCandidateHealthObservation,
    ModelCandidateHealthStatus,
)
from azents.repos.model_candidate_selection import select_model_operation_candidate
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)


@pytest.mark.parametrize("has_alternate", [False, True])
async def test_healthy_model_remains_assigned_despite_incompatible_controls(
    has_alternate: bool,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    selection = make_test_model_selection(model_identifier="assigned-model")
    selection.normalized_capabilities.reasoning.supported = False
    selection.normalized_capabilities.reasoning.effort_levels = []
    selection.supported_execution_options = []
    candidates = [
        SelectableModelCandidate(
            model_selection=selection, settings=make_test_model_settings()
        )
    ]
    if has_alternate:
        alternate = make_test_model_selection(model_identifier="must-not-switch")
        alternate.normalized_capabilities.reasoning.supported = True
        alternate.normalized_capabilities.reasoning.effort_levels = [
            ModelReasoningEffort.HIGH
        ]
        alternate.supported_execution_options = [ModelExecutionOptionId.FAST]
        candidates.append(
            SelectableModelCandidate(
                model_selection=alternate, settings=make_test_model_settings()
            )
        )
    profile = RequestedInferenceProfile(
        model_target_label="Quality",
        reasoning_effort=ModelReasoningEffort.HIGH,
        enabled_execution_options=[ModelExecutionOptionId.FAST],
    )
    operation = build_model_operation(
        option=SelectableModelOption(
            label="Quality",
            candidates=candidates,
            subagent_enabled=True,
            subagent_guidance=None,
        ),
        profile=profile,
        kind=ModelOperationKind.FOREGROUND,
        operation_id="o" * 32,
        recorded_at=now,
    )
    health = AsyncMock(spec=ModelCandidateHealthRepository)
    health.claim_foreground_probe_in_session.return_value = ForegroundProbeResult(
        outcome=ForegroundProbeOutcome.HEALTHY,
        observation=ModelCandidateHealthObservation(
            server_time=now, status=ModelCandidateHealthStatus.AVAILABLE, health=None
        ),
    )
    result = await select_model_operation_candidate(
        AsyncMock(spec=AsyncSession),
        operation=operation,
        workspace_id="workspace",
        health_repository=health,
        recorded_at=now,
        session_id="session",
        reservation=None,
    )
    assert result.candidate.model_selection.model_identifier == "assigned-model"
    assert result.operation.cursor == 0
    assert result.operation.requested_reasoning_effort == ModelReasoningEffort.HIGH
    assert result.operation.requested_execution_options == [ModelExecutionOptionId.FAST]
    assert health.claim_foreground_probe_in_session.await_count == 1
