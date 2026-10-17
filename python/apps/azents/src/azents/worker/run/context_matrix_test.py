"""Exact context-limit branches through native fresh-turn preparation."""

from unittest.mock import AsyncMock

import pytest
from azcommon.result import Success

from azents.core.agent import SelectableModelSettings
from azents.core.enums import AgentRunStatus, EventKind
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.engine.events import execution_test as event_fixtures
from azents.engine.events.execution import AgentRunExecutionRequest
from azents.engine.events.types import TurnMarkerPayload
from azents.engine.run import resolve_test as resolve_fixtures
from azents.engine.run.input import InvokeInput
from azents.engine.run.turn_action_bridge import TurnActionBridgeBoundary
from azents.repos.engine_resolve import get_engine_resolve_repositories
from azents.repos.toolkit import ToolkitRepository
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)
from azents.testing.model_stream import make_test_model_stream_watchdog
from azents.worker.run import executor_test as executor_fixtures


@pytest.mark.parametrize(
    (
        "label",
        "model",
        "default_input",
        "maximum_input",
        "user_cap",
        "effective",
        "threshold",
    ),
    [
        ("default", "gpt-5.5", 96_000, 256_000, None, 96_000, 86_400),
        ("extended", "gpt-5.5", 96_000, 256_000, 160_000, 160_000, 144_000),
        ("clamped", "gpt-5.5", 96_000, 256_000, 300_000, 256_000, 230_400),
        ("legacy", "gpt-5.5-mini", None, 512_000, None, 512_000, 460_800),
    ],
)
async def test_context_limit_matrix_reaches_prepared_inference_state(
    label: str,
    model: str,
    default_input: int | None,
    maximum_input: int,
    user_cap: int | None,
    effective: int,
    threshold: int,
) -> None:
    """Use the real model resolver and Worker preparation for every exact branch."""
    selection = make_test_model_selection(
        integration_id="integ-1", model_identifier=model
    )
    window = selection.normalized_capabilities.context_window
    window.default_input_tokens = default_input
    window.max_input_tokens = maximum_input
    option = make_test_selectable_model_options(selection, label=label)[0]
    option.candidates[0].settings = SelectableModelSettings(
        context_window_tokens=user_cap,
        max_output_tokens=None,
        builtin_tools=[],
    )
    lightweight = make_test_model_selection(
        integration_id="integ-1", model_identifier="gpt-5.5-mini"
    )
    lightweight.normalized_capabilities.context_window.default_input_tokens = None
    lightweight.normalized_capabilities.context_window.max_input_tokens = 512_000
    lightweight_option = make_test_selectable_model_options(
        lightweight, label="summary"
    )[0]
    agent = resolve_fixtures._make_agent().model_copy(
        update={
            "id": "agent-001",
            "model_selection": selection,
            "lightweight_model_selection": lightweight,
            "selectable_model_options": [option, lightweight_option],
            "main_model_label": label,
            "lightweight_model_label": "summary",
        }
    )
    executor = executor_fixtures._executor(agent=agent)
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = agent
    integration_repository = AsyncMock()
    integration_repository.get_by_id_with_secrets.return_value = (
        resolve_fixtures._make_integration()
    )
    executor.resolve_repositories = get_engine_resolve_repositories(
        setting_payloads=AsyncMock(spec=SystemSettingPayloadResolver),
        session_manager=resolve_fixtures._session_manager_for(
            resolve_fixtures._resolution_session()
        ),
        agent_repository=agent_repository,
        integration_repository=integration_repository,
        toolkit_repository=ToolkitRepository(cipher=None),
    )

    prepared = await executor._prepare_fresh_main_model_turn(
        agent_id="agent-001",
        session_id="session-001",
        run_id="run-001",
        owner_generation=1,
        invoke_input=InvokeInput(
            agent_id="agent-001", session_id="session-001", messages=[]
        ),
        override=None,
    )

    assert isinstance(prepared, Success)
    request = prepared.value.run_request
    state = prepared.value.inference_state
    assert request.model == model
    assert request.context_window_tokens == user_cap
    assert request.max_input_tokens == effective
    assert request.compaction_max_input_tokens == 512_000
    assert request.effective_max_input_tokens == effective
    assert state.model_target_label == label
    assert state.model_settings.context_window_tokens == user_cap
    assert state.effective_context_window_tokens == effective
    assert state.effective_auto_compaction_threshold_tokens == threshold
    route = state.applied_model_route
    assert route is not None
    assert route.model_identifier == model
    assert route.effective_context_window_tokens == effective
    assert route.effective_auto_compaction_threshold_tokens == threshold
    assert executor.test_session_state.inference_state == state

    transcript = event_fixtures._TranscriptRepo()
    execution = event_fixtures._execution(
        input_recovery_sink=None,
        session_manager=event_fixtures._session_context,
        input_projection_repository=None,
        terminal_finalization_repository=None,
        metadata_repository=event_fixtures._OutputMetadataRepository(failure=None),
        model_operation_completion=None,
        post_lower_filter=event_fixtures._PostFilter(),
        model_stream_watchdog=make_test_model_stream_watchdog(),
        model_stream_provider="test",
        model_stream_provider_integration_id=None,
        model_stream_inference_profile=None,
        model_adapter=event_fixtures._ModelAdapter(),
        output_normalizer=event_fixtures._Normalizer(
            [event_fixtures._assistant_event()]
        ),
        model_call_preparer=event_fixtures._model_call_preparer(inference_state=state),
        run_repo=event_fixtures._RunRepo(),
        transcript_repo=transcript,
    )
    status = await execution.run(
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=event_fixtures._OpenToolAdmissionBarrier(),
            turn_action_bridge_boundary=TurnActionBridgeBoundary(),
            run_id="run-1",
            session_id="session-1",
            model=model,
        )
    )
    assert status is AgentRunStatus.COMPLETED
    markers = [
        event for event in transcript.events if event.kind is EventKind.TURN_MARKER
    ]
    assert len(markers) == 1
    marker = markers[0].payload
    assert isinstance(marker, TurnMarkerPayload)
    assert marker.applied_inference_profile == state.applied_profile
    assert marker.effective_context_window_tokens == effective
    assert marker.effective_auto_compaction_threshold_tokens == threshold
