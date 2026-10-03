"""An explicitly captured context view is never replaced inside a resolver."""

from collections.abc import Sequence
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.run import resolve_test as fixtures
from azents.engine.run.input import InvokeInput
from azents.engine.run.resolve import (
    resolve_invoke_input_with_profile,
    resolve_invoke_input_with_resolved_profile,
    resolve_model_candidate_runtime,
)
from azents.repos.chatgpt_oauth_runtime import ChatGPTOAuthRuntimeRepository
from azents.repos.engine_read import EngineModelReadRepository
from azents.repos.engine_resolve import get_engine_resolve_repositories
from azents.repos.kimi_oauth_runtime import KimiOAuthRuntimeRepository
from azents.repos.model_metadata_source_data import (
    CapturedContextSource,
    ContextModelMetadata,
    ContextModelRequest,
)
from azents.repos.toolkit import ToolkitRepository
from azents.repos.xai_oauth_runtime import XaiOAuthRuntimeRepository
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver
from azents.services.model_metadata import ModelMetadataService
from azents.services.oauth_runtime_clients import create_runtime_oauth_client_factories
from azents.testing.model_metadata import (
    make_test_model_metadata_service,
    make_test_source,
    make_test_source_payload,
)


class _ForbidContextRecapture(ModelMetadataService):
    async def capture_for_context(
        self, *, requests: Sequence[ContextModelRequest]
    ) -> CapturedContextSource:
        del requests
        raise AssertionError("The caller already captured this context authority.")


@pytest.mark.parametrize("operation", ["profile", "frozen", "runtime"])
@pytest.mark.parametrize("absent", [False, True])
async def test_real_resolver_respects_captured_context_even_when_new_source_exists(
    monkeypatch: pytest.MonkeyPatch,
    operation: Literal["profile", "frozen", "runtime"],
    absent: bool,
) -> None:
    """An empty narrow capture is absence, not an instruction to read again."""
    agent = fixtures._make_agent()
    candidate = agent.selectable_model_options[0].candidates[0]
    integration = fixtures._make_integration()
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = agent
    integration_repository = AsyncMock()
    integration_repository.get_by_id_with_secrets.return_value = integration
    session_manager = fixtures._session_manager_for(AsyncMock(spec=AsyncSession))
    latest = make_test_model_metadata_service(
        source=make_test_source(
            make_test_source_payload(
                {"gpt-4o": {"litellm_provider": "openai", "max_input_tokens": 400_000}}
            )
        )
    )
    metadata = _ForbidContextRecapture(
        repository=latest.repository,
    )
    captured = CapturedContextSource(
        models=(
            ()
            if absent
            else (
                ContextModelMetadata(
                    provider=LLMProvider.OPENAI,
                    model_identifier="gpt-4o",
                    max_input_tokens=96_000,
                ),
            )
        )
    )
    monkeypatch.setattr(
        EngineRuntimeTokenResolver,
        "ensure",
        AsyncMock(return_value=Success(integration)),
    )
    if operation == "runtime":
        runtime = await resolve_model_candidate_runtime(
            agent_id=agent.id,
            workspace_id=agent.workspace_id,
            selection=candidate.model_selection,
            settings=candidate.settings,
            context_source=captured,
            model_metadata_service=metadata,
            model_read_repository=EngineModelReadRepository(
                integration_repository=integration_repository,
                session_manager=session_manager,
            ),
            runtime_token_resolver=EngineRuntimeTokenResolver(
                oauth_clients=create_runtime_oauth_client_factories(),
                chatgpt_repository=ChatGPTOAuthRuntimeRepository(
                    integration_repository=integration_repository,
                    session_manager=session_manager,
                ),
                xai_repository=XaiOAuthRuntimeRepository(
                    integration_repository=integration_repository,
                    session_manager=session_manager,
                ),
                kimi_repository=KimiOAuthRuntimeRepository(
                    integration_repository=integration_repository,
                    session_manager=session_manager,
                ),
            ),
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
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=fixtures._make_image_generation_catalog_service(),
            model_metadata_service=metadata,
            repositories=get_engine_resolve_repositories(
                session_manager=session_manager,
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
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
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=fixtures._make_image_generation_catalog_service(),
            model_metadata_service=metadata,
            repositories=get_engine_resolve_repositories(
                session_manager=session_manager,
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )
        assert isinstance(frozen, Success)
        request = frozen.value
    expected = 128_000 if absent else 96_000
    assert request.max_input_tokens == expected
    assert request.compaction_max_input_tokens == expected
