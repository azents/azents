"""Availability projection follows quota health, not raw control compatibility."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.inference_profile import SessionAppliedInferenceProfile
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.rdb.session_capabilities import ReadOnlySession, ReadSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import (
    ModelCandidateHealthObservation,
    ModelCandidateHealthStatus,
)
from azents.repos.session_model_availability import (
    SessionModelAvailabilityRepository,
    _AuthorizedAvailabilityContext,
)
from azents.repos.session_model_profile.repository import SessionModelProfileRepository
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)
from azents.worker.run import executor_test as fixtures


@asynccontextmanager
async def _read_scope() -> AsyncIterator[ReadSession]:
    async with AsyncSession() as session:
        yield ReadOnlySession(session)


@pytest.mark.parametrize("requested_effort", [None, ModelReasoningEffort.HIGH])
@pytest.mark.parametrize("requested_fast", [False, True])
@pytest.mark.parametrize(
    "first_status",
    [
        ModelCandidateHealthStatus.AVAILABLE,
        ModelCandidateHealthStatus.COOLDOWN,
        ModelCandidateHealthStatus.CLAIMED,
        ModelCandidateHealthStatus.RECOVERY_PENDING,
    ],
)
async def test_projection_reports_first_healthy_fallback_despite_raw_controls(
    requested_effort: ModelReasoningEffort | None,
    requested_fast: bool,
    first_status: ModelCandidateHealthStatus,
) -> None:
    primary = make_test_model_selection(model_identifier="primary")
    option = make_test_selectable_model_options(primary)[0]
    for identifier in ("first-fallback", "second-fallback"):
        selection = make_test_model_selection(model_identifier=identifier)
        selection.normalized_capabilities.reasoning.supported = False
        selection.normalized_capabilities.reasoning.effort_levels = []
        selection.supported_execution_options = []
        option.candidates.extend(
            make_test_selectable_model_options(selection)[0].candidates
        )
    agent = fixtures._default_agent().model_copy(
        update={"model_selection": primary, "selectable_model_options": [option]}
    )
    profile = SessionAppliedInferenceProfile(
        model_target_label="default",
        reasoning_effort=requested_effort,
        enabled_execution_options=(
            [ModelExecutionOptionId.FAST] if requested_fast else []
        ),
    )
    session = fixtures._default_agent_session(
        inference_state=None, applied_inference_profile=profile
    )
    context = _AuthorizedAvailabilityContext(
        session=session,
        agent=agent,
        semantic_label="default",
        primary=option.candidates[0],
    )
    health = AsyncMock(spec=ModelCandidateHealthRepository)
    now = datetime.datetime.now(datetime.UTC)
    health.snapshot_in_session.return_value = ModelCandidateHealthObservation(
        server_time=now, status=ModelCandidateHealthStatus.COOLDOWN, health=None
    )
    health.snapshot_for_background_in_session.side_effect = [
        ModelCandidateHealthObservation(
            server_time=now, status=first_status, health=None
        ),
        ModelCandidateHealthObservation(
            server_time=now, status=ModelCandidateHealthStatus.AVAILABLE, health=None
        ),
    ]
    repository = SessionModelAvailabilityRepository(
        read_session_manager=_read_scope,
        session_manager=Mock(),
        agent_repository=AsyncMock(spec=AgentRepository),
        agent_session_repository=AsyncMock(spec=AgentSessionRepository),
        session_model_profile_repository=AsyncMock(spec=SessionModelProfileRepository),
        health_repository=health,
    )

    result = await repository._project(context)

    first_available = first_status is ModelCandidateHealthStatus.AVAILABLE
    assert result.first_usable_fallback_display_name == (
        "first-fallback" if first_available else "second-fallback"
    )
    assert result.state == "cooldown"
    assert result.primary.model_identifier == "primary"
    assert session.applied_inference_profile == profile
    assert [
        call.args[1].model_identifier
        for call in health.snapshot_for_background_in_session.await_args_list
    ] == (
        ["first-fallback"] if first_available else ["first-fallback", "second-fallback"]
    )
    health.claim_foreground_probe_in_session.assert_not_awaited()
