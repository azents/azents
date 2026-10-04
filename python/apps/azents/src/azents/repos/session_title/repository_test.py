"""Session title operation repository tests."""

import datetime
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.active_model_capabilities import (
    ActiveModelCapabilitiesUnavailable,
    ActiveModelMetadataUnavailable,
    CapturedStoredChoice,
    ConfiguredModelIdentity,
)
from azents.core.agent import AgentModelSelection
from azents.core.enums import AgentSessionTitleSource
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.model_catalog_identity import catalog_source_keys
from azents.core.model_catalog_source import decode_catalog_source
from azents.core.model_operation import ModelOperationKind, build_model_operation
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
    ModelProviderFailureRetryability,
)
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs
from azents.repos.model_candidate_health.data import (
    ModelCandidateHealthObservation,
    ModelCandidateHealthStatus,
)
from azents.repos.session_title import SessionTitleRepository
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)


@pytest.mark.parametrize("mode", ["new", "reuse", "quota", "drift", "unavailable"])
async def test_load_generation_snapshot_freezes_title_operation_in_one_context(
    mode: str,
) -> None:
    """The title owner, chain selection, and persistence share one transaction."""
    events: list[str] = []
    session: AsyncSession = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        events.append("enter")
        try:
            yield session
        finally:
            events.append("exit")

    agent_session = SimpleNamespace(
        agent_id="agent-1",
        title_source=AgentSessionTitleSource.AUTO_INITIAL,
        title_generation_event_id="event-1",
        title_model_operation_state=None,
    )
    agent_session_repository = AsyncMock()
    agent_session_repository.lock_by_id.return_value = agent_session
    agent_session_repository.set_title_model_operation_state.return_value = (
        agent_session
    )
    selection = make_test_model_selection(integration_id="integration-1")
    raw_selection = selection.model_dump(mode="json")
    raw_selection["normalized_capabilities"] = _legacy_v2_capabilities()
    selection = AgentModelSelection.model_validate(raw_selection)
    options = make_test_selectable_model_options(selection)
    if mode == "reuse":
        agent_session.title_model_operation_state = build_model_operation(
            option=options[0],
            profile=RequestedInferenceProfile(
                model_target_label=options[0].label,
                reasoning_effort=None,
                enabled_execution_options=[],
            ),
            kind=ModelOperationKind.TITLE,
            operation_id="f" * 32,
            recorded_at=datetime.datetime.now(datetime.UTC),
        )
    agent_repository = AsyncMock()
    agent_repository.lock_by_id.return_value = SimpleNamespace(
        id="agent-1",
        workspace_id="workspace-1",
        lightweight_model_label="default",
        selectable_model_options=options,
    )
    agent_repository.get_by_id.return_value = agent_repository.lock_by_id.return_value
    health_repository = AsyncMock()
    now = datetime.datetime.now(datetime.UTC)
    health_repository.snapshot_for_background_in_session.return_value = (
        ModelCandidateHealthObservation(
            server_time=now,
            status=ModelCandidateHealthStatus.AVAILABLE,
            health=None,
        )
    )
    active_metadata = _active_metadata_repository(structured_output=True)
    if mode == "drift":
        active_metadata.inputs_match_in_session.return_value = False
    if mode == "unavailable":
        active_metadata.capture_exact_choices_in_session.side_effect = None
        active_metadata.capture_exact_choices_in_session.return_value = (
            CapturedActiveChoiceInputs(
                workspace_id="workspace-1",
                choices=(
                    ActiveModelMetadataUnavailable(
                        ConfiguredModelIdentity.from_selection(selection),
                        "exact_entry_unavailable",
                    ),
                ),
                catalog_choices=(),
                source_metadata=None,
                source_expectations=(),
            )
        )
    repository = SessionTitleRepository(
        agent_repository=agent_repository,
        agent_session_repository=agent_session_repository,
        health_repository=health_repository,
        active_capabilities_repository=active_metadata,
        session_manager=session_manager,
    )

    if mode == "unavailable":
        with pytest.raises(ActiveModelCapabilitiesUnavailable):
            await repository.load_generation_snapshot(
                session_id="session-1", generation_event_id="event-1"
            )
        agent_session_repository.set_title_model_operation_state.assert_not_awaited()
        return
    snapshot = await repository.load_generation_snapshot(
        session_id="session-1",
        generation_event_id="event-1",
    )

    if mode == "drift":
        assert snapshot is None
        agent_session_repository.set_title_model_operation_state.assert_not_awaited()
        return
    assert snapshot is not None
    assert snapshot.agent_id == "agent-1"
    assert snapshot.workspace_id == "workspace-1"
    assert snapshot.operation.kind is ModelOperationKind.TITLE
    captured_selection = snapshot.operation.current_candidate.model_selection
    assert captured_selection.model_identifier == selection.model_identifier
    assert (
        captured_selection.llm_provider_integration_id
        == selection.llm_provider_integration_id
    )
    assert captured_selection.normalized_capabilities.tool_calling.supported == (
        mode != "reuse"
    )
    assert (
        snapshot.operation.current_candidate.settings
        == options[0].candidates[0].settings
    )
    assert selection.normalized_capabilities.tool_calling.supported is False
    if mode == "reuse":
        active_metadata.capture_exact_choices_in_session.assert_not_awaited()
        active_metadata.inputs_match_in_session.assert_not_awaited()
    else:
        active_metadata.capture_exact_choices_in_session.assert_awaited_once()
        active_metadata.inputs_match_in_session.assert_awaited_once()
    if mode == "quota":
        active_metadata.reset_mock()
        active_metadata.capture_exact_choices_in_session.side_effect = AssertionError(
            "Title quota progression must not query current model metadata."
        )
        agent_session.title_model_operation_state = snapshot.operation
        health_repository.renew_quota_in_session.return_value = (
            ModelCandidateHealthObservation(
                server_time=now,
                status=ModelCandidateHealthStatus.AVAILABLE,
                health=None,
            )
        )
        result = await repository.advance_after_quota(
            session_id="session-1",
            generation_event_id="event-1",
            failure=ModelProviderFailure(
                operation="session_title",
                category=ModelProviderFailureCategory.QUOTA_OR_BILLING,
                retryability=ModelProviderFailureRetryability.USER_ACTION_REQUIRED,
                provider_message=None,
                status_code=429,
                provider_code=None,
                provider_error_type=None,
                provider_error_param=None,
                retry_hint_seconds=None,
                provider=captured_selection.provider.value,
                integration=captured_selection.llm_provider_integration_id,
                model=captured_selection.model_identifier,
            ),
        )
        assert result is None
        active_metadata.capture_exact_choices_in_session.assert_not_awaited()
        active_metadata.inputs_match_in_session.assert_not_awaited()
        return
    assert events == ["enter", "exit"]
    agent_session_repository.lock_by_id.assert_awaited_once_with(
        session,
        "session-1",
    )
    agent_repository.lock_by_id.assert_awaited_once_with(session, "agent-1")
    agent_session_repository.set_title_model_operation_state.assert_awaited_once()


async def test_replace_initial_auto_title_commits_as_one_repository_operation() -> None:
    """The conditional title update receives one repository-owned session."""
    events: list[str] = []
    session: AsyncSession = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        events.append("enter")
        try:
            yield session
        finally:
            events.append("exit")

    agent_session_repository = AsyncMock()
    updated = SimpleNamespace(id="session-1")
    agent_session_repository.replace_initial_auto_title.return_value = updated
    repository = SessionTitleRepository(
        agent_repository=AsyncMock(),
        agent_session_repository=agent_session_repository,
        health_repository=AsyncMock(),
        active_capabilities_repository=_active_metadata_repository(
            structured_output=True
        ),
        session_manager=session_manager,
    )

    result = await repository.replace_initial_auto_title(
        session_id="session-1",
        title="Incident response",
        event_id="event-1",
    )

    assert result is updated
    assert events == ["enter", "exit"]
    agent_session_repository.replace_initial_auto_title.assert_awaited_once_with(
        session,
        session_id="session-1",
        title="Incident response",
        event_id="event-1",
    )


def _active_metadata_repository(*, structured_output: bool) -> AsyncMock:
    """Capture synthetic exact declarations, never the saved capability object."""
    repository = AsyncMock(spec=ActiveModelCapabilitiesRepository)

    async def capture(
        session: AsyncSession,
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
