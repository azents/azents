"""Image-generation catalog service tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import NamedTuple

import pytest
from azcommon.result import Success
from cryptography.fernet import Fernet

import azents.services.image_generation_catalog as image_generation_catalog_module
from azents.core.agent import BuiltinToolConfig, SelectableModelSettings
from azents.core.credentials import ApiKeySecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogEntryVisibility,
    LLMCatalogPurpose,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog_sync import (
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncTrigger,
)
from azents.core.workspace import WorkspaceCreate
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.image_generation_catalog_operations import (
    ImageGenerationCatalogOperationsRepository,
)
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    ImageGenerationCatalogEntryCreate,
    IntegrationCatalogSyncClaim,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationUpdate,
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.workspace import WorkspaceRepository
from azents.services.image_generation_catalog import (
    ImageGenerationCatalogService,
    default_only_image_generation_catalog,
    image_generation_default_available,
    image_generation_explicit_selection_supported,
)
from azents.services.model_listing.data import ImageGenerationModelListingOutput
from azents.services.model_listing.providers import (
    ListingClientFactories,
    ListingProviderError,
    create_listing_client_factories,
)
from azents.testing.model_selection import make_test_model_selection


class _ImageCatalogServiceFixture(NamedTuple):
    """Image catalog service test fixture."""

    service: ImageGenerationCatalogService
    integration_repository: LLMProviderIntegrationRepository
    workspace_id: str
    integration_id: str


def test_default_only_provider_returns_no_catalog_or_discovery_state() -> None:
    """ChatGPT OAuth remains default-only until explicit visibility is verified."""
    result = default_only_image_generation_catalog(
        provider=LLMProvider.CHATGPT_OAUTH,
        integration_enabled=True,
    )

    assert result.default_available is True
    assert result.explicit_selection_supported is False
    assert result.catalog_id is None
    assert result.entries == []
    assert result.total == 0
    assert result.usable is True


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
    session: WriteSession,
) -> SessionManager[WriteSession]:
    """Return a test session manager over the active transaction."""

    @asynccontextmanager
    async def manager() -> AsyncGenerator[WriteSession, None]:
        yield session

    return manager


async def _create_service(
    rdb_session: WriteSession,
    *,
    handle: str,
) -> _ImageCatalogServiceFixture:
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
        operations=ImageGenerationCatalogOperationsRepository(
            session_manager=_session_manager_for(rdb_session),
            read_session_manager=_session_manager_for(rdb_session),
            catalog_repository=LLMCatalogRepository(),
            integration_repository=integration_repository,
        ),
        listing_clients=create_listing_client_factories(),
    )
    return _ImageCatalogServiceFixture(
        service=service,
        integration_repository=integration_repository,
        workspace_id=workspace_id,
        integration_id=integration.id,
    )


async def _publish_flare(
    service: ImageGenerationCatalogService,
    *,
    rdb_session: WriteSession,
    workspace_id: str,
    integration_id: str,
) -> None:
    """Publish one current Flare entry through credential fencing."""
    catalog = await service.operations.catalog_repository.ensure_integration_catalog(
        rdb_session,
        integration_id=integration_id,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.IMAGE_GENERATION,
    )
    started_at = datetime.datetime.now(datetime.UTC)
    claim = await service.operations.catalog_repository.begin_integration_sync(
        rdb_session,
        catalog_id=catalog.id,
        workspace_id=workspace_id,
        started_at=started_at,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
        required_projection_version=None,
    )
    assert isinstance(claim, IntegrationCatalogSyncClaim)
    publication = await service.operations.publish(
        catalog=catalog,
        claim=claim,
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
                projection_metadata=None,
                hidden_reason=None,
            )
        ],
        diagnostics={"catalog_purpose": "image_generation"},
        sync_diagnostics={"catalog_purpose": "image_generation"},
        finished_at=started_at + datetime.timedelta(seconds=1),
        fetched_count=1,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )
    assert publication.published


@pytest.mark.asyncio
async def test_sync_uses_credential_snapshot_loaded_after_attempt_claim(
    rdb_session: WriteSession,
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
    original_begin_attempt = (
        service.operations.catalog_repository.begin_integration_sync
    )

    async def begin_attempt_after_credential_update(
        session: WriteSession,
        *,
        catalog_id: str,
        workspace_id: str,
        started_at: datetime.datetime,
        trigger: IntegrationCatalogSyncTrigger,
        required_projection_version: None,
    ) -> IntegrationCatalogSyncClaim | IntegrationCatalogSyncPolicyDecision:
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
            started_at=started_at,
            trigger=trigger,
            required_projection_version=required_projection_version,
        )

    async def list_models_from_claimed_credentials(
        integration: LLMProviderIntegrationWithSecrets,
        *,
        clients: ListingClientFactories,
    ) -> ImageGenerationModelListingOutput:
        assert integration.secrets == ApiKeySecrets(api_key="sk-updated")
        return ImageGenerationModelListingOutput(
            provider=LLMProvider.OPENAI,
            source="openai:models_list",
            fetched_at=datetime.datetime.now(datetime.UTC),
            provider_model_identifiers=["gpt-image-2.5-flare"],
        )

    monkeypatch.setattr(
        service.operations.catalog_repository,
        "begin_integration_sync",
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
async def test_disabled_conversation_without_image_tool_has_no_image_gate(
    rdb_session: WriteSession,
) -> None:
    """Conversation-only saves retain their existing selection predicates."""
    fixture = await _create_service(
        rdb_session, handle="disabled-conversation-without-image"
    )
    disabled = await fixture.integration_repository.update_by_id(
        rdb_session, fixture.integration_id, {"enabled": False}
    )
    assert isinstance(disabled, Success)
    errors = await fixture.service.validate_option(
        workspace_id=fixture.workspace_id,
        selection=make_test_model_selection(integration_id=fixture.integration_id),
        settings=SelectableModelSettings(
            context_window_tokens=None,
            max_output_tokens=None,
            builtin_tools=[],
        ),
    )
    assert errors == []


@pytest.mark.asyncio
@pytest.mark.parametrize("automatic_retry_blocked", [False, True])
async def test_sync_provider_failure_is_visible_after_failed_attempt_commit(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    automatic_retry_blocked: bool,
) -> None:
    """Record the failure before propagation without replacing last-good authority."""
    async with rdb_session_manager() as session:
        fixture = await _create_service(
            session,
            handle=f"image-service-provider-failure-{int(automatic_retry_blocked)}",
        )
        await _publish_flare(
            fixture.service,
            rdb_session=session,
            workspace_id=fixture.workspace_id,
            integration_id=fixture.integration_id,
        )
    service = replace(
        fixture.service,
        operations=replace(
            fixture.service.operations, session_manager=rdb_session_manager
        ),
    )
    before = await service.operations.read(
        integration_id=fixture.integration_id, workspace_id=fixture.workspace_id
    )
    assert before is not None and before.page is not None
    failure = ListingProviderError(
        "Provider image listing is unavailable.",
        automatic_retry_blocked=automatic_retry_blocked,
    )
    cause = RuntimeError("Provider transport failed.")

    async def failing_listing(
        integration: LLMProviderIntegrationWithSecrets,
        *,
        clients: ListingClientFactories,
    ) -> ImageGenerationModelListingOutput:
        del integration, clients
        raise failure from cause

    clock = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
    monkeypatch.setattr(image_generation_catalog_module, "_utcnow", lambda: clock)
    monkeypatch.setattr(
        image_generation_catalog_module,
        "list_openai_image_generation_models_for_integration",
        failing_listing,
    )
    with pytest.raises(ListingProviderError) as caught:
        await service.sync(
            integration_id=fixture.integration_id,
            workspace_id=fixture.workspace_id,
            trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
        )
    assert caught.value is failure
    assert caught.value.__cause__ is cause

    after = await service.operations.read(
        integration_id=fixture.integration_id, workspace_id=fixture.workspace_id
    )
    assert after is not None and after.page is not None
    sync_status = after.page.catalog.sync_status
    assert sync_status is not None
    assert sync_status.status is LLMCatalogAttemptStatus.FAILED
    assert sync_status.finished_at == clock
    assert sync_status.failure_code == "RuntimeError"
    assert sync_status.failure_message == str(failure)
    assert sync_status.diagnostics is not None
    assert sync_status.diagnostics["automatic_retry_blocked"] is automatic_retry_blocked
    assert after.page.catalog.last_success_at == before.page.catalog.last_success_at
    assert after.page.catalog.image_usable == before.page.catalog.image_usable
    assert after.page.catalog.visible_count == before.page.catalog.visible_count
    assert after.page.catalog.hidden_count == before.page.catalog.hidden_count
    assert after.page.entries == before.page.entries
    assert (
        after.integration.catalog_configuration_version
        == before.integration.catalog_configuration_version
    )


@pytest.mark.asyncio
async def test_explicit_pin_requires_current_catalog_usability(
    rdb_session: WriteSession,
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
    assert runtime_error.reason == "catalog_unusable"
    assert runtime_error.model_identifier == "gpt-image-2.5-flare"


@pytest.mark.asyncio
async def test_disabled_integration_rejects_default_with_recovery_guidance(
    rdb_session: WriteSession,
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
    rdb_session: WriteSession,
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
