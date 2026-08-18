"""Integration model catalog projection tests."""

import datetime

import httpx
import pytest
from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

import azents.services.llm_catalog as llm_catalog_service
from azents.core.credentials import ApiKeySecrets, XaiOAuthConfig, XaiOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import LLMCatalogEntryVisibility, LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelBuiltInToolCapabilities,
    ModelCapabilities,
    ModelCompatibilityCapabilities,
    ModelContextWindow,
    ModelModalities,
    ModelModality,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
)
from azents.core.llm_catalog_sync import IntegrationCatalogSyncTrigger
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import (
    LiteLLMSourceSnapshotRepository,
    LLMCatalogRepository,
)
from azents.repos.llm_catalog.data import LiteLLMSourceSnapshot
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.services.llm_catalog import (
    IntegrationCatalogProjectionService,
    LiteLLMSourceLoader,
    LiteLLMSourceSyncService,
    project_chatgpt_integration_entries,
    project_integration_entries,
    project_kimi_integration_entries,
    project_openrouter_integration_entries,
    project_xai_integration_entries,
)
from azents.services.model_listing.data import (
    ModelListingOutput,
    ModelListingSummary,
    NormalizedModelCandidate,
)


def test_project_integration_entries_requires_exact_target_projection() -> None:
    """Integration projection exposes exact matches and hides missing target keys."""
    fetched_at = datetime.datetime.now(datetime.UTC)
    listing = ModelListingOutput(
        models=[
            NormalizedModelCandidate(
                provider=LLMProvider.AWS_BEDROCK,
                model_identifier="anthropic.claude-3-haiku-20240307-v1:0",
                model_display_name="Claude 3 Haiku",
                model_developer=LLMModelDeveloper.ANTHROPIC,
                model_family="claude",
                normalized_capabilities=ModelCapabilities(),
                model_snapshot={},
                source_metadata=None,
                last_refreshed_at=fetched_at,
            ),
            NormalizedModelCandidate(
                provider=LLMProvider.AWS_BEDROCK,
                model_identifier="unmatched.model-v1",
                model_display_name="Unmatched",
                model_developer=LLMModelDeveloper.ANTHROPIC,
                model_family="unmatched",
                normalized_capabilities=ModelCapabilities(),
                model_snapshot={},
                source_metadata=None,
                last_refreshed_at=fetched_at,
            ),
        ],
        summary=ModelListingSummary(
            source="aws_bedrock:list_foundation_models",
            fetched_at=fetched_at,
            returned_count=2,
            skipped_count=0,
        ),
        skips=[],
    )
    source_snapshot = LiteLLMSourceSnapshot(
        id="source-id",
        source_key="litellm_model_cost",
        source_url=None,
        source_hash="hash",
        model_count=1,
        litellm_version="1.0.0",
        loaded_source="fixture",
        payload={
            "bedrock/anthropic.claude-3-haiku-20240307-v1:0": {
                "litellm_provider": "bedrock",
                "mode": "chat",
                "supports_function_calling": True,
            }
        },
        created_at=fetched_at,
    )

    entries = project_integration_entries(
        integration_id="integration-id",
        provider=LLMProvider.AWS_BEDROCK,
        listing=listing,
        source_snapshot=source_snapshot,
    )

    assert entries[0].visibility_status == LLMCatalogEntryVisibility.SELECTABLE
    assert entries[0].runtime_model_identifier == (
        "bedrock/anthropic.claude-3-haiku-20240307-v1:0"
    )
    assert entries[1].visibility_status == LLMCatalogEntryVisibility.HIDDEN
    assert entries[1].hidden_reason == "missing_target_projection"


def test_project_chatgpt_entries_does_not_require_litellm_metadata() -> None:
    """ChatGPT backend models remain selectable without LiteLLM projection keys."""
    fetched_at = datetime.datetime.now(datetime.UTC)
    listing = ModelListingOutput(
        models=[
            NormalizedModelCandidate(
                provider=LLMProvider.CHATGPT_OAUTH,
                model_identifier="gpt-5.6-luna",
                model_display_name="GPT-5.6 Luna",
                model_developer=LLMModelDeveloper.OPENAI,
                model_family="gpt-5.6",
                normalized_capabilities=ModelCapabilities(
                    compatibility=ModelCompatibilityCapabilities(
                        provider_family="chatgpt",
                        responses_api=True,
                    )
                ),
                model_snapshot={},
                source_metadata={"context_window": 272000},
                last_refreshed_at=fetched_at,
            )
        ],
        summary=ModelListingSummary(
            source="chatgpt:codex_models",
            fetched_at=fetched_at,
            returned_count=1,
            skipped_count=0,
        ),
        skips=[],
    )

    entries = project_chatgpt_integration_entries(
        integration_id="integration-id",
        listing=listing,
    )

    [entry] = entries
    assert entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
    assert entry.runtime_model_identifier == "gpt-5.6-luna"
    assert entry.normalized_capabilities["compatibility"] == {
        "provider_family": "chatgpt",
        "responses_api": True,
        "unsupported_media_policy": None,
    }
    assert entry.projection_metadata == {
        "lowerer_target": "litellm",
        "freshness_rank": 5060,
    }
    assert entry.source_metadata is not None
    assert "source_hash" not in entry.source_metadata


def test_project_kimi_entries_does_not_require_litellm_metadata() -> None:
    """Kimi account models remain selectable without target metadata."""
    fetched_at = datetime.datetime.now(datetime.UTC)
    listing = ModelListingOutput(
        models=[
            NormalizedModelCandidate(
                provider=LLMProvider.KIMI_OAUTH,
                model_identifier="kimi-k2.5",
                model_display_name="Kimi K2.5",
                model_developer=LLMModelDeveloper.MOONSHOT,
                model_family="kimi-k2.5",
                normalized_capabilities=ModelCapabilities(
                    compatibility=ModelCompatibilityCapabilities(
                        provider_family="moonshot",
                        responses_api=True,
                    )
                ),
                model_snapshot={},
                source_metadata={"context_length": 262144},
                last_refreshed_at=fetched_at,
            )
        ],
        summary=ModelListingSummary(
            source="kimi:code_models",
            fetched_at=fetched_at,
            returned_count=1,
            skipped_count=0,
        ),
        skips=[],
    )

    entries = project_kimi_integration_entries(
        integration_id="integration-id",
        listing=listing,
    )

    [entry] = entries
    assert entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
    assert entry.provider_model_identifier == "kimi-k2.5"
    assert entry.runtime_model_identifier == "moonshot/kimi-k2.5"
    assert entry.publisher == "moonshot"
    assert entry.hidden_reason is None
    assert entry.projection_metadata == {
        "lowerer_target": "litellm",
        "target_metadata_match_required": False,
        "freshness_rank": 2050,
    }
    assert entry.source_metadata is not None
    assert "source_hash" not in entry.source_metadata


def test_project_openrouter_entries_does_not_require_litellm_metadata() -> None:
    """OpenRouter account models remain selectable without target metadata."""
    fetched_at = datetime.datetime.now(datetime.UTC)
    listing = ModelListingOutput(
        models=[
            NormalizedModelCandidate(
                provider=LLMProvider.OPENROUTER,
                model_identifier="new-publisher/new-model",
                model_display_name="New Model",
                model_developer=LLMModelDeveloper.OTHER,
                model_family="new",
                normalized_capabilities=ModelCapabilities(
                    compatibility=ModelCompatibilityCapabilities(
                        provider_family="openrouter",
                        responses_api=True,
                    )
                ),
                model_snapshot={},
                source_metadata={"supported_parameters": []},
                last_refreshed_at=fetched_at,
            )
        ],
        summary=ModelListingSummary(
            source="openrouter:account_models",
            fetched_at=fetched_at,
            returned_count=1,
            skipped_count=0,
        ),
        skips=[],
    )

    entries = project_openrouter_integration_entries(
        integration_id="integration-id",
        listing=listing,
    )

    [entry] = entries
    assert entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
    assert entry.provider_model_identifier == "new-publisher/new-model"
    assert entry.runtime_model_identifier == "openrouter/new-publisher/new-model"
    assert entry.publisher == "other"
    assert entry.hidden_reason is None
    assert entry.projection_metadata == {
        "lowerer_target": "litellm",
        "target_metadata_match_required": False,
        "freshness_rank": 0,
    }
    assert entry.source_metadata is not None
    assert "source_hash" not in entry.source_metadata


def test_project_xai_entries_preserves_provider_authority_and_enriches_gaps() -> None:
    """Provider capabilities win while LiteLLM fills omitted capability fields."""
    fetched_at = datetime.datetime.now(datetime.UTC)
    listing = ModelListingOutput(
        models=[
            NormalizedModelCandidate(
                provider=LLMProvider.XAI_OAUTH,
                model_identifier="grok-4.6",
                model_display_name="Grok 4.6",
                model_developer=LLMModelDeveloper.XAI,
                model_family="grok-4",
                normalized_capabilities=ModelCapabilities(
                    context_window=ModelContextWindow(max_input_tokens=500000),
                    modalities=ModelModalities(
                        input=[ModelModality.TEXT],
                        output=[ModelModality.TEXT],
                    ),
                    reasoning=ModelReasoningCapabilities(
                        supported=True,
                        effort_levels=[
                            ModelReasoningEffort.LOW,
                            ModelReasoningEffort.MEDIUM,
                            ModelReasoningEffort.HIGH,
                            ModelReasoningEffort.XHIGH,
                        ],
                    ),
                    built_in_tools=ModelBuiltInToolCapabilities(
                        supported=["web_search"]
                    ),
                    compatibility=ModelCompatibilityCapabilities(
                        provider_family="xai",
                        responses_api=True,
                    ),
                ),
                model_snapshot={},
                source_metadata={
                    "context_window": 500000,
                    "api_backend": "responses",
                    "supports_reasoning_effort": True,
                    "reasoning_efforts": [{"id": "xhigh"}],
                    "supports_backend_search": True,
                },
                last_refreshed_at=fetched_at,
            )
        ],
        summary=ModelListingSummary(
            source="xai_oauth:grok_models",
            fetched_at=fetched_at,
            returned_count=1,
            skipped_count=0,
        ),
        skips=[],
    )
    source_snapshot = LiteLLMSourceSnapshot(
        id="source-id",
        source_key="litellm_model_cost",
        source_url=None,
        source_hash="source-hash",
        model_count=1,
        litellm_version="1.0.0",
        loaded_source="fixture",
        payload={
            "xai/grok-4.6": {
                "litellm_provider": "xai",
                "mode": "chat",
                "max_input_tokens": 131072,
                "max_output_tokens": 32768,
                "supports_function_calling": True,
                "supports_reasoning": False,
                "supports_web_search": False,
                "input_cost_per_token": 0.000001,
                "output_cost_per_token": 0.000002,
                "provider_internal_note": "must not be retained",
            }
        },
        created_at=fetched_at,
    )

    entries = project_xai_integration_entries(
        integration_id="oauth-integration",
        provider=LLMProvider.XAI_OAUTH,
        listing=listing,
        source_snapshot=source_snapshot,
    )

    [entry] = entries
    assert entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
    assert entry.runtime_model_identifier == "xai/grok-4.6"
    capabilities = entry.normalized_capabilities
    assert capabilities["context_window"] == {
        "max_input_tokens": 500000,
        "max_output_tokens": 32768,
    }
    assert capabilities["reasoning"]["supported"] is True
    assert capabilities["reasoning"]["effort_levels"] == [
        "low",
        "medium",
        "high",
        "xhigh",
    ]
    assert capabilities["tool_calling"]["supported"] is True
    assert capabilities["built_in_tools"]["supported"] == [
        "web_search",
        "image_generation",
    ]
    assert capabilities["compatibility"]["responses_api"] is True
    assert entry.projection_metadata is not None
    assert entry.projection_metadata["matched"] is True
    assert entry.source_metadata is not None
    assert entry.source_metadata["target_metadata"] == {
        "input_cost_per_token": 0.000001,
        "output_cost_per_token": 0.000002,
    }


def test_project_xai_entries_keeps_unmatched_provider_model_selectable() -> None:
    """Missing LiteLLM metadata remains diagnostic instead of hiding the model."""
    fetched_at = datetime.datetime.now(datetime.UTC)
    listing = ModelListingOutput(
        models=[
            NormalizedModelCandidate(
                provider=LLMProvider.XAI,
                model_identifier="grok-new-account-only",
                model_display_name="grok-new-account-only",
                model_developer=LLMModelDeveloper.XAI,
                model_family="grok-new",
                normalized_capabilities=ModelCapabilities(
                    modalities=ModelModalities(
                        input=[ModelModality.TEXT],
                        output=[ModelModality.TEXT],
                    ),
                    compatibility=ModelCompatibilityCapabilities(
                        provider_family="xai",
                        responses_api=None,
                    ),
                ),
                model_snapshot={},
                source_metadata={"created": 1, "owned_by": "xai"},
                last_refreshed_at=fetched_at,
            )
        ],
        summary=ModelListingSummary(
            source="xai:developer_models",
            fetched_at=fetched_at,
            returned_count=1,
            skipped_count=0,
        ),
        skips=[],
    )

    entries = project_xai_integration_entries(
        integration_id="api-key-integration",
        provider=LLMProvider.XAI,
        listing=listing,
        source_snapshot=None,
    )

    [entry] = entries
    assert entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
    assert entry.hidden_reason is None
    assert entry.normalized_capabilities["tool_calling"]["supported"] is False
    assert entry.normalized_capabilities["reasoning"]["supported"] is False
    assert entry.normalized_capabilities["built_in_tools"]["supported"] == []
    assert entry.projection_metadata is not None
    assert entry.projection_metadata["matched"] is False


def test_project_xai_entries_ignores_malformed_optional_enrichment() -> None:
    """Malformed LiteLLM metadata cannot gate provider-authoritative visibility."""
    fetched_at = datetime.datetime.now(datetime.UTC)
    listing = ModelListingOutput(
        models=[
            NormalizedModelCandidate(
                provider=LLMProvider.XAI,
                model_identifier="grok-provider-only",
                model_display_name="grok-provider-only",
                model_developer=LLMModelDeveloper.XAI,
                model_family="grok-provider",
                normalized_capabilities=ModelCapabilities(
                    modalities=ModelModalities(
                        input=[ModelModality.TEXT],
                        output=[ModelModality.TEXT],
                    )
                ),
                model_snapshot={},
                source_metadata={"created": 1},
                last_refreshed_at=fetched_at,
            )
        ],
        summary=ModelListingSummary(
            source="xai:developer_models",
            fetched_at=fetched_at,
            returned_count=1,
            skipped_count=0,
        ),
        skips=[],
    )
    source_snapshot = LiteLLMSourceSnapshot(
        id="source-id",
        source_key="litellm_model_cost",
        source_url=None,
        source_hash="source-hash",
        model_count=1,
        litellm_version="1.0.0",
        loaded_source="fixture",
        payload={
            "xai/grok-provider-only": {
                "litellm_provider": "xai",
                "supports_reasoning": {"invalid": "shape"},
            }
        },
        created_at=fetched_at,
    )

    entries = project_xai_integration_entries(
        integration_id="api-key-integration",
        provider=LLMProvider.XAI,
        listing=listing,
        source_snapshot=source_snapshot,
    )

    [entry] = entries
    assert entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
    assert entry.normalized_capabilities["reasoning"]["supported"] is False
    assert entry.projection_metadata is not None
    assert entry.projection_metadata["matched"] is False
    assert entry.source_metadata is not None
    assert entry.source_metadata["target_metadata"] is None


async def test_deterministic_integration_sync_does_not_require_source_authority(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Sync direct integration projections without a LiteLLM source snapshot."""
    async with rdb_session_manager() as session:
        workspace_result = await WorkspaceRepository().create(
            session,
            WorkspaceCreate(
                name="Direct catalog workspace",
                handle="direct-catalog-workspace",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await WorkspaceRepository().resolve_id(
            session,
            "direct-catalog-workspace",
        )
        assert workspace_id is not None

        integration_repository = LLMProviderIntegrationRepository(
            CredentialCipher(Fernet.generate_key().decode())
        )
        integration = await integration_repository.create(
            session,
            LLMProviderIntegrationCreate(
                workspace_id=workspace_id,
                provider=LLMProvider.OPENROUTER,
                name="__testenv_model_listing:deterministic-openrouter",
                secrets=ApiKeySecrets(api_key="fixture"),
                config=None,
                enabled=True,
            ),
        )

    def unexpected_source_request(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected LiteLLM source request: {request.url}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(unexpected_source_request)
    ) as client:
        result = await IntegrationCatalogProjectionService(
            session_manager=rdb_session_manager,
            catalog_repository=LLMCatalogRepository(),
            integration_repository=integration_repository,
            source_sync_service=LiteLLMSourceSyncService(
                session_manager=rdb_session_manager,
                snapshot_repository=LiteLLMSourceSnapshotRepository(),
                source_loader=LiteLLMSourceLoader(
                    http_client=client,
                    source_url="https://catalog.example.test/models.json",
                    litellm_version="1.91.3",
                ),
            ),
        ).sync_integration_catalog(
            integration_id=integration.id,
            workspace_id=workspace_id,
        )

    assert isinstance(result, Success)
    assert result.value.snapshot_id is not None
    assert result.value.visible_count == 2


async def test_xai_oauth_sync_refreshes_before_listing(
    rdb_session_manager: SessionManager[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the persisted OAuth refresh lifecycle before provider discovery."""
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        workspace_result = await WorkspaceRepository().create(
            session,
            WorkspaceCreate(
                name="xAI OAuth catalog workspace",
                handle="xai-oauth-catalog-workspace",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await WorkspaceRepository().resolve_id(
            session,
            "xai-oauth-catalog-workspace",
        )
        assert workspace_id is not None
        integration_repository = LLMProviderIntegrationRepository(
            CredentialCipher(Fernet.generate_key().decode())
        )
        created_integration = await integration_repository.create(
            session,
            LLMProviderIntegrationCreate(
                workspace_id=workspace_id,
                provider=LLMProvider.XAI_OAUTH,
                name="xAI Grok OAuth",
                secrets=XaiOAuthSecrets(
                    access_token="expired-token",
                    refresh_token="refresh-token",
                    expires_at=now - datetime.timedelta(minutes=1),
                ),
                config=XaiOAuthConfig(
                    account_id="account-id",
                    email=None,
                    connection_method="device",
                    status="connected",
                    connected_at=now,
                    last_refreshed_at=now,
                ),
                enabled=True,
            ),
        )
        integration = await integration_repository.get_by_id_with_secrets(
            session,
            created_integration.id,
        )
        assert integration is not None

    call_order: list[str] = []

    async def ensure_tokens(**kwargs: object) -> Success:
        del kwargs
        call_order.append("refresh")
        return Success(
            integration.model_copy(
                update={
                    "secrets": XaiOAuthSecrets(
                        access_token="fresh-token",
                        refresh_token="rotated-refresh-token",
                        expires_at=now + datetime.timedelta(hours=1),
                    )
                }
            )
        )

    async def list_models(
        listed_integration: LLMProviderIntegrationWithSecrets,
    ) -> ModelListingOutput:
        call_order.append("list")
        assert isinstance(listed_integration.secrets, XaiOAuthSecrets)
        assert listed_integration.secrets.access_token == "fresh-token"
        return ModelListingOutput(
            models=[
                NormalizedModelCandidate(
                    provider=LLMProvider.XAI_OAUTH,
                    model_identifier="grok-4.6",
                    model_display_name="Grok 4.6",
                    model_developer=LLMModelDeveloper.XAI,
                    model_family="grok-4",
                    normalized_capabilities=ModelCapabilities(
                        modalities=ModelModalities(
                            input=[ModelModality.TEXT],
                            output=[ModelModality.TEXT],
                        )
                    ),
                    model_snapshot={},
                    source_metadata={"context_window": 500000},
                    last_refreshed_at=now,
                )
            ],
            summary=ModelListingSummary(
                source="xai_oauth:grok_models",
                fetched_at=now,
                returned_count=1,
                skipped_count=0,
            ),
            skips=[],
        )

    monkeypatch.setattr(llm_catalog_service, "ensure_xai_runtime_tokens", ensure_tokens)
    monkeypatch.setattr(
        llm_catalog_service,
        "_list_provider_visible_models",
        list_models,
    )

    async with httpx.AsyncClient() as client:
        result = await IntegrationCatalogProjectionService(
            session_manager=rdb_session_manager,
            catalog_repository=LLMCatalogRepository(),
            integration_repository=integration_repository,
            source_sync_service=LiteLLMSourceSyncService(
                session_manager=rdb_session_manager,
                snapshot_repository=LiteLLMSourceSnapshotRepository(),
                source_loader=LiteLLMSourceLoader(
                    http_client=client,
                    source_url="https://catalog.example.test/models.json",
                    litellm_version="1.91.3",
                ),
            ),
        ).sync_integration_catalog(
            integration_id=integration.id,
            workspace_id=workspace_id,
            trigger=IntegrationCatalogSyncTrigger.CREATE,
        )

    assert isinstance(result, Success)
    assert result.value.visible_count == 1
    assert call_order == ["refresh", "list"]


async def test_xai_failure_preserves_last_successful_snapshot(
    rdb_session_manager: SessionManager[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the published xAI catalog when a later provider refresh fails."""
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        workspace_result = await WorkspaceRepository().create(
            session,
            WorkspaceCreate(
                name="xAI failure workspace",
                handle="xai-failure-workspace",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await WorkspaceRepository().resolve_id(
            session,
            "xai-failure-workspace",
        )
        assert workspace_id is not None
        integration_repository = LLMProviderIntegrationRepository(
            CredentialCipher(Fernet.generate_key().decode())
        )
        integration = await integration_repository.create(
            session,
            LLMProviderIntegrationCreate(
                workspace_id=workspace_id,
                provider=LLMProvider.XAI,
                name="xAI API key",
                secrets=ApiKeySecrets(api_key="secret-api-key"),
                config=None,
                enabled=True,
            ),
        )

    listing = ModelListingOutput(
        models=[
            NormalizedModelCandidate(
                provider=LLMProvider.XAI,
                model_identifier="grok-4.7",
                model_display_name="grok-4.7",
                model_developer=LLMModelDeveloper.XAI,
                model_family="grok-4",
                normalized_capabilities=ModelCapabilities(
                    modalities=ModelModalities(
                        input=[ModelModality.TEXT],
                        output=[ModelModality.TEXT],
                    )
                ),
                model_snapshot={},
                source_metadata={"created": 1, "owned_by": "xai"},
                last_refreshed_at=now,
            )
        ],
        summary=ModelListingSummary(
            source="xai:developer_models",
            fetched_at=now,
            returned_count=1,
            skipped_count=0,
        ),
        skips=[],
    )
    calls = 0

    async def list_models(integration_value: object) -> ModelListingOutput:
        nonlocal calls
        del integration_value
        calls += 1
        if calls == 1:
            return listing
        raise llm_catalog_service.XaiListingProviderError(
            failure_code="XaiEntitlementDenied",
            automatic_retry_blocked=True,
        )

    monkeypatch.setattr(
        llm_catalog_service,
        "_list_provider_visible_models",
        list_models,
    )
    catalog_repository = LLMCatalogRepository()
    async with httpx.AsyncClient() as client:
        service = IntegrationCatalogProjectionService(
            session_manager=rdb_session_manager,
            catalog_repository=catalog_repository,
            integration_repository=integration_repository,
            source_sync_service=LiteLLMSourceSyncService(
                session_manager=rdb_session_manager,
                snapshot_repository=LiteLLMSourceSnapshotRepository(),
                source_loader=LiteLLMSourceLoader(
                    http_client=client,
                    source_url="https://catalog.example.test/models.json",
                    litellm_version="1.91.3",
                ),
            ),
        )
        first = await service.sync_integration_catalog(
            integration_id=integration.id,
            workspace_id=workspace_id,
            trigger=IntegrationCatalogSyncTrigger.CREATE,
        )
        assert isinstance(first, Success)
        first_snapshot_id = first.value.snapshot_id
        failed = await service.sync_integration_catalog(
            integration_id=integration.id,
            workspace_id=workspace_id,
            trigger=IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
        )

    assert isinstance(failed, Success)
    assert failed.value.status == "failed"
    assert failed.value.snapshot_id == first_snapshot_id
    assert failed.value.failure_code == "XaiEntitlementDenied"
    assert failed.value.failure_message == "xAI model listing failed."
    async with rdb_session_manager() as session:
        catalog = await catalog_repository.get_by_integration(
            session,
            integration_id=integration.id,
            workspace_id=workspace_id,
        )
        assert catalog is not None
        assert catalog.current_snapshot_id == first_snapshot_id
        latest_attempt = await catalog_repository.get_latest_attempt(
            session,
            catalog=catalog,
        )
    assert latest_attempt is not None
    assert latest_attempt.diagnostics is not None
    assert latest_attempt.diagnostics["automatic_retry_blocked"] is True
    assert "secret-api-key" not in str(latest_attempt.diagnostics)
