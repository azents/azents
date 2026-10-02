"""An explicitly captured context view is never replaced inside a resolver."""

import dataclasses
from collections.abc import Sequence
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.run import resolve as resolve_module
from azents.engine.run import resolve_test as fixtures
from azents.engine.run.input import InvokeInput
from azents.engine.run.resolve import (
    resolve_invoke_input_with_profile,
    resolve_invoke_input_with_resolved_profile,
    resolve_model_candidate_runtime,
)
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.model_metadata import CapturedContextSource, ModelMetadataService
from azents.testing.model_metadata import (
    make_test_model_metadata_service,
    make_test_source_payload,
    make_test_source_snapshot,
)


class _ForbidContextRecapture(ModelMetadataService):
    async def capture_for_context(
        self, *, capability_maximums: Sequence[int | None]
    ) -> ModelMetadataSourceSnapshot | None:
        del capability_maximums
        raise AssertionError("The caller already captured this context authority.")


def _snapshot(identifier: str, maximum: int) -> ModelMetadataSourceSnapshot:
    payload = make_test_source_payload(
        {"gpt-4o": {"litellm_provider": "openai", "max_input_tokens": maximum}}
    )
    return dataclasses.replace(make_test_source_snapshot(payload), id=identifier)


@pytest.mark.parametrize("operation", ["profile", "frozen", "runtime"])
@pytest.mark.parametrize("absent", [False, True])
async def test_real_resolver_respects_captured_context_even_when_new_source_exists(
    monkeypatch: pytest.MonkeyPatch,
    operation: Literal["profile", "frozen", "runtime"],
    absent: bool,
) -> None:
    """Captured None is absence, not an instruction to read the now-new snapshot."""
    agent = fixtures._make_agent()
    candidate = agent.selectable_model_options[0].candidates[0]
    integration = fixtures._make_integration()
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = agent
    integration_repository = AsyncMock()
    integration_repository.get_by_id_with_secrets.return_value = integration
    session_manager = fixtures._session_manager_for(AsyncMock(spec=AsyncSession))
    latest = make_test_model_metadata_service(snapshot=_snapshot("B", 400_000))
    metadata = _ForbidContextRecapture(
        session_manager=latest.session_manager,
        source_snapshot_repository=latest.source_snapshot_repository,
    )
    captured = CapturedContextSource(
        snapshot=None if absent else _snapshot("A", 96_000)
    )
    monkeypatch.setattr(
        resolve_module,
        "_ensure_provider_runtime_tokens",
        AsyncMock(return_value=Success(integration)),
    )
    if operation == "runtime":
        runtime = await resolve_model_candidate_runtime(
            agent_id=agent.id,
            workspace_id=agent.workspace_id,
            selection=candidate.model_selection,
            settings=candidate.settings,
            context_source=captured,
            integration_repository=integration_repository,
            session_manager=session_manager,
            model_metadata_service=metadata,
        )
        assert isinstance(runtime, Success)
        assert runtime.value.effective_input_tokens == (128_000 if absent else 96_000)
        return
    invoke_input = InvokeInput(agent_id=agent.id, session_id="session-1", messages=[])
    if operation == "profile":
        profile = await resolve_invoke_input_with_profile(
            invoke_input,
            context_source=captured,
            requested_profile=RequestedInferenceProfile(
                model_target_label="default",
                reasoning_effort=None,
                enabled_execution_options=[],
            ),
            agent_repository=agent_repository,
            integration_repository=integration_repository,
            session_manager=session_manager,
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=fixtures._make_image_generation_catalog_service(),
            model_metadata_service=metadata,
        )
        assert isinstance(profile, Success)
        request = profile.value.run_request
    else:
        frozen = await resolve_invoke_input_with_resolved_profile(
            invoke_input,
            context_source=captured,
            resolved_model_selection=candidate.model_selection,
            resolved_model_settings=candidate.settings,
            resolved_reasoning_effort=None,
            resolved_enabled_execution_options=[],
            agent_repository=agent_repository,
            integration_repository=integration_repository,
            session_manager=session_manager,
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=fixtures._make_image_generation_catalog_service(),
            model_metadata_service=metadata,
        )
        assert isinstance(frozen, Success)
        request = frozen.value
    expected = 128_000 if absent else 96_000
    assert request.max_input_tokens == expected
    assert request.compaction_max_input_tokens == expected
