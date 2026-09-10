"""Image-generation catalog service tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

import azents.services.image_generation_catalog as image_generation_catalog_module
from azents.core.agent import BuiltinToolConfig, SelectableModelSettings
from azents.core.credentials import ApiKeySecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMCatalogLowererTarget,
    LLMCatalogPurpose,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog_sync import (
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncTrigger,
)
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import ImageGenerationCatalogEntryCreate
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationUpdate,
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.services.image_generation_catalog import (
    ImageGenerationCatalogService,
    default_only_image_generation_catalog,
    image_generation_default_available,
    image_generation_explicit_selection_supported,
)
from azents.services.model_listing.data import ImageGenerationModelListingOutput
from azents.testing.model_selection import make_test_model_selection


def test_default_only_provider_returns_no_catalog_or_discovery_state() -> None:
    """ChatGPT OAuth remains default-only until explicit visibility is verified."""
    result = default_only_image_generation_catalog(
        provider=LLMProvider.CHATGPT_OAUTH,
        integration_enabled=True,
        current_configuration_version=3,
    )

    assert result.default_available is True
    assert result.explicit_selection_supported is False
    assert result.catalog_id is None
    assert result.entries == []
    assert result.total == 0
    assert result.current_configuration_version == 3
    assert result.generation_current is True


def test_disabled_default_provider_is_not_available() -> None:
    """Disabling the integration disables both default and explicit dispatch."""
    assert not image_generation_default_available(
        provider=LLMProvider.OPENAI,
        integration_enabled=False,
    )


def test_only_openai_api_key_supports_explicit_image_selection_initially() -> None:
    """Other existing image paths retain maintained default-only behavior."""
    assert image_generation_explicit_selection_supported(LLMProvider.OPENAI)
    assert not image_generation_explicit_selection_supported(LLMProvider.CHATGPT_OAUTH)
    assert not image_generation_explicit_selection_supported(LLMProvider.XAI)
    assert not image_generation_explicit_selection_supported(LLMProvider.XAI_OAUTH)


def _session_manager_for(
    session: AsyncSession,
) -> SessionManager[AsyncSession]:
    """Return a test session manager over the active transaction."""

    @asynccontextmanager
    async def manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    return manager


async def _create_service(
    rdb_session: AsyncSession,
    *,
    handle: str,
) -> tuple[
    ImageGenerationCatalogService,
    LLMProviderIntegrationRepository,
    str,
    str,
]:
    """Create a service backed by one OpenAI integration."""
    workspace_repository = WorkspaceRepository()
    workspace_result = await workspace_repository.create(
        rdb_session,
        WorkspaceCreate(name=f"{handle} workspace", handle=handle),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await workspace_repository.resolve_id(rdb_session, handle)
    assert workspace_id is not None
    integration_repository = LLMProviderIntegrationRepository(
        CredentialCipher(Fernet.generate_key().decode())
    )
    integration = await integration_repository.create(
        rdb_session,
        LLMProviderIntegrationCreate(
            workspace_id=workspace_id,
            provider=LLMProvider.OPENAI,
            name="OpenAI",
            secrets=ApiKeySecrets(api_key="sk-test"),
        ),
    )
    service = ImageGenerationCatalogService(
        session_manager=_session_manager_for(rdb_session),
        catalog_repository=LLMCatalogRepository(),
        integration_repository=integration_repository,
    )
    return service, integration_repository, workspace_id, integration.id


async def _publish_flare(
    service: ImageGenerationCatalogService,
    *,
    rdb_session: AsyncSession,
    workspace_id: str,
    integration_id: str,
) -> None:
    """Publish one current-generation Flare entry through repository fencing."""
    catalog = await service.catalog_repository.ensure_integration_catalog(
        rdb_session,
        integration_id=integration_id,
        provider=LLMProvider.OPENAI,
        lowerer_target=LLMCatalogLowererTarget.LITELLM,
        purpose=LLMCatalogPurpose.IMAGE_GENERATION,
    )
    started_at = datetime.datetime.now(datetime.UTC)
    attempt_id = await service.catalog_repository.begin_integration_attempt(
        rdb_session,
        catalog_id=catalog.id,
        workspace_id=workspace_id,
        source_key="openai_models_list:image_generation",
        started_at=started_at,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )
    assert isinstance(attempt_id, str)
    publication = (
        await service.catalog_repository.replace_current_image_generation_snapshot(
            rdb_session,
            catalog=catalog,
            attempt_id=attempt_id,
            entries=[
                ImageGenerationCatalogEntryCreate(
                    provider=LLMProvider.OPENAI,
                    provider_model_identifier="gpt-image-2.5-flare",
                    display_name="GPT Image 2.5 Flare",
                    description="Recommended image model.",
                    recommendation_rank=1,
                    lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                    visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                    provider_integration_id=integration_id,
                    source_metadata=None,
                    projection_metadata={"registry_revision": 1},
                    hidden_reason=None,
                )
            ],
            diagnostics={"catalog_purpose": "image_generation"},
        )
    )
    assert publication.snapshot_id is not None
    await service.catalog_repository.mark_attempt_succeeded(
        rdb_session,
        attempt_id=attempt_id,
        finished_at=started_at + datetime.timedelta(seconds=1),
        produced_snapshot_id=publication.snapshot_id,
        fetched_count=1,
        matched_count=1,
        skipped_count=0,
        hidden_count=0,
        diagnostics={"catalog_purpose": "image_generation"},
    )


@pytest.mark.asyncio
async def test_sync_uses_credential_snapshot_loaded_after_attempt_claim(
    rdb_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A credential update before claim cannot publish the older credential view."""
    (
        service,
        integration_repository,
        workspace_id,
        integration_id,
    ) = await _create_service(
        rdb_session,
        handle="image-service-credential-snapshot",
    )
    original_begin_attempt = service.catalog_repository.begin_integration_attempt

    async def begin_attempt_after_credential_update(
        session: AsyncSession,
        *,
        catalog_id: str,
        workspace_id: str,
        source_key: str,
        started_at: datetime.datetime,
        trigger: IntegrationCatalogSyncTrigger,
    ) -> str | IntegrationCatalogSyncPolicyDecision:
        update_result = await integration_repository.update_by_id(
            rdb_session,
            integration_id,
            LLMProviderIntegrationUpdate(
                secrets=ApiKeySecrets(api_key="sk-updated"),
            ),
        )
        assert isinstance(update_result, Success)
        return await original_begin_attempt(
            session,
            catalog_id=catalog_id,
            workspace_id=workspace_id,
            source_key=source_key,
            started_at=started_at,
            trigger=trigger,
        )

    async def list_models_from_claimed_credentials(
        integration: LLMProviderIntegrationWithSecrets,
    ) -> ImageGenerationModelListingOutput:
        assert integration.secrets == ApiKeySecrets(api_key="sk-updated")
        return ImageGenerationModelListingOutput(
            provider=LLMProvider.OPENAI,
            source="openai:models_list",
            fetched_at=datetime.datetime.now(datetime.UTC),
            provider_model_identifiers=["gpt-image-2.5-flare"],
        )

    monkeypatch.setattr(
        service.catalog_repository,
        "begin_integration_attempt",
        begin_attempt_after_credential_update,
    )
    monkeypatch.setattr(
        image_generation_catalog_module,
        "list_openai_image_generation_models_for_integration",
        list_models_from_claimed_credentials,
    )

    result = await service.sync(
        integration_id=integration_id,
        workspace_id=workspace_id,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )

    assert isinstance(result, Success)
    assert result.value.visible_count == 1


@pytest.mark.asyncio
async def test_explicit_pin_requires_current_catalog_generation(
    rdb_session: AsyncSession,
) -> None:
    """Saved and runtime pins stop authorizing after credential generation changes."""
    (
        service,
        integration_repository,
        workspace_id,
        integration_id,
    ) = await _create_service(
        rdb_session,
        handle="image-service-generation",
    )
    await _publish_flare(
        service,
        rdb_session=rdb_session,
        workspace_id=workspace_id,
        integration_id=integration_id,
    )
    selection = make_test_model_selection(integration_id=integration_id)
    selection.normalized_capabilities.built_in_tools.supported = ["image_generation"]
    settings = SelectableModelSettings(
        context_window_tokens=None,
        max_output_tokens=None,
        builtin_tools=[
            BuiltinToolConfig(
                name="image_generation",
                config={"model": "gpt-image-2.5-flare", "quality": "high"},
            )
        ],
        subagent_enabled=True,
        subagent_guidance=None,
    )

    assert (
        await service.validate_option(
            workspace_id=workspace_id,
            selection=selection,
            settings=settings,
        )
        == []
    )
    update_result = await integration_repository.update_by_id(
        rdb_session,
        integration_id,
        LLMProviderIntegrationUpdate(
            secrets=ApiKeySecrets(api_key="sk-updated"),
        ),
    )
    assert isinstance(update_result, Success)

    assert await service.validate_option(
        workspace_id=workspace_id,
        selection=selection,
        settings=settings,
    ) == [
        "Refresh the image model catalog, choose an available model, "
        "or use the default."
    ]
    runtime_error = await service.validate_runtime(
        integration_id=integration_id,
        workspace_id=workspace_id,
        provider=LLMProvider.OPENAI,
        integration_enabled=True,
        image_generation_supported=True,
        settings=settings,
    )
    assert runtime_error is not None
    assert runtime_error.reason == "catalog_generation_mismatch"
    assert runtime_error.model_identifier == "gpt-image-2.5-flare"


@pytest.mark.asyncio
async def test_disabled_integration_rejects_default_with_recovery_guidance(
    rdb_session: AsyncSession,
) -> None:
    """Disabling an integration blocks maintained-default save and execution."""
    (
        service,
        integration_repository,
        workspace_id,
        integration_id,
    ) = await _create_service(
        rdb_session,
        handle="image-service-disabled",
    )
    update_result = await integration_repository.update_by_id(
        rdb_session,
        integration_id,
        LLMProviderIntegrationUpdate(enabled=False),
    )
    assert isinstance(update_result, Success)
    selection = make_test_model_selection(integration_id=integration_id)
    selection.normalized_capabilities.built_in_tools.supported = ["image_generation"]
    settings = SelectableModelSettings(
        context_window_tokens=None,
        max_output_tokens=None,
        builtin_tools=[BuiltinToolConfig(name="image_generation", config={})],
        subagent_enabled=True,
        subagent_guidance=None,
    )

    assert await service.validate_option(
        workspace_id=workspace_id,
        selection=selection,
        settings=settings,
    ) == ["Enable the provider integration before using image generation."]
    runtime_error = await service.validate_runtime(
        integration_id=integration_id,
        workspace_id=workspace_id,
        provider=LLMProvider.OPENAI,
        integration_enabled=False,
        image_generation_supported=True,
        settings=settings,
    )
    assert runtime_error is not None
    assert runtime_error.reason == "integration_disabled"
    assert runtime_error.model_identifier is None


@pytest.mark.asyncio
async def test_runtime_rejects_image_tool_missing_from_conversation_capabilities(
    rdb_session: AsyncSession,
) -> None:
    """A reconstructed selection cannot bypass current image capability checks."""
    service, _, workspace_id, integration_id = await _create_service(
        rdb_session,
        handle="image-service-runtime-capability",
    )
    settings = SelectableModelSettings(
        context_window_tokens=None,
        max_output_tokens=None,
        builtin_tools=[
            BuiltinToolConfig(
                name="image_generation",
                config={"model": "gpt-image-2.5-flare"},
            )
        ],
        subagent_enabled=True,
        subagent_guidance=None,
    )

    runtime_error = await service.validate_runtime(
        integration_id=integration_id,
        workspace_id=workspace_id,
        provider=LLMProvider.OPENAI,
        integration_enabled=True,
        image_generation_supported=False,
        settings=settings,
    )

    assert runtime_error is not None
    assert runtime_error.reason == "model_unavailable"
    assert runtime_error.model_identifier == "gpt-image-2.5-flare"
