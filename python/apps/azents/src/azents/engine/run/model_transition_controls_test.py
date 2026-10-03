"""Effective reasoning is validated before dispatch to a frozen assigned model."""

from unittest.mock import AsyncMock

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import ModelParameters
from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_capability_projection import project_capabilities
from azents.core.model_catalog_source import CatalogFact
from azents.engine.run.input import InvokeInput
from azents.engine.run.resolve import resolve_invoke_input_with_resolved_profile
from azents.engine.run.resolve_test import (
    _make_agent,
    _make_image_generation_catalog_service,
    _make_integration,
    _session_manager_for,
)
from azents.repos.engine_resolve import get_engine_resolve_repositories
from azents.repos.toolkit import ToolkitRepository
from azents.services.engine_runtime_tokens import create_runtime_oauth_client_factories
from azents.testing.model_metadata import make_test_model_metadata_service
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)


@pytest.mark.parametrize("applied", [ModelReasoningEffort.MEDIUM, None])
async def test_frozen_model_validates_effective_not_raw_agent_effort(
    applied: ModelReasoningEffort | None,
) -> None:
    agent = _make_agent(
        reasoning_supported=True, effort_levels=[ModelReasoningEffort.HIGH]
    )
    agent.model_parameters = ModelParameters(reasoning_effort=ModelReasoningEffort.HIGH)
    frozen = make_test_model_selection(
        integration_id="integ-1", model_identifier="frozen-assigned-model"
    )
    frozen.normalized_capabilities = project_capabilities(
        provider=LLMProvider.OPENAI,
        exact_model="frozen-assigned-model",
        source_model=None,
        model_developer=None,
        evidence=ProviderCapabilityEvidence(
            reasoning=CatalogFact(state="value", value=applied is not None),
            reasoning_efforts=CatalogFact(
                state="value", value=(applied,) if applied is not None else ()
            ),
        ),
    )
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = agent
    integrations = AsyncMock()
    integrations.get_by_id_with_secrets.return_value = _make_integration()
    manager = _session_manager_for(AsyncMock(spec=AsyncSession))
    result = await resolve_invoke_input_with_resolved_profile(
        InvokeInput(agent_id="agent-1", session_id="session-1", messages=[]),
        resolved_model_selection=frozen,
        resolved_model_settings=make_test_model_settings(),
        context_source=None,
        resolved_reasoning_effort=applied,
        resolved_enabled_execution_options=[],
        repositories=get_engine_resolve_repositories(
            agent_repository=agent_repository,
            integration_repository=integrations,
            session_manager=manager,
            toolkit_repository=ToolkitRepository(cipher=None),
        ),
        oauth_clients=create_runtime_oauth_client_factories(),
        exchange_file_service=AsyncMock(),
        model_file_service=AsyncMock(),
        image_generation_catalog_service=_make_image_generation_catalog_service(),
        model_metadata_service=make_test_model_metadata_service(snapshot=None),
    )
    assert isinstance(result, Success)
    assert result.value.reasoning_effort == applied
    assert result.value.model == "frozen-assigned-model"
    assert result.value.enabled_execution_options == []
    assert agent.model_parameters.reasoning_effort == ModelReasoningEffort.HIGH
