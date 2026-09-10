"""LLM catalog repository tests."""

import datetime

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import (
    ApiKeySecrets,
    ChatGPTOAuthConfig,
    ChatGPTOAuthSecrets,
)
from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMCatalogLowererTarget,
    LLMCatalogPurpose,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog import ModelCapabilities
from azents.core.llm_catalog_sync import (
    IntegrationCatalogSyncDenialReason,
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncTrigger,
)
from azents.rdb.models.llm_catalog import RDBLLMCatalogEntry, RDBLLMCatalogSnapshot
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    ImageGenerationCatalogEntryCreate,
    LLMCatalogEntryCreate,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationUpdate,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

pytestmark = pytest.mark.asyncio


async def _create_openai_integration(
    rdb_session: AsyncSession,
    *,
    handle: str,
) -> tuple[str, LLMProviderIntegrationRepository, str]:
    """Create an OpenAI integration and return its workspace and repositories."""
    workspace_repository = WorkspaceRepository()
    workspace_result = await workspace_repository.create(
        rdb_session,
        WorkspaceCreate(
            name=f"{handle} workspace",
            handle=handle,
        ),
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
    return workspace_id, integration_repository, integration.id


async def test_replace_current_snapshot_persists_snapshot_before_entries(
    rdb_session: AsyncSession,
) -> None:
    """Snapshot replacement should satisfy entry snapshot FK ordering."""
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        lowerer_target=LLMCatalogLowererTarget.LITELLM,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )

    snapshot_id = await repository.replace_current_snapshot(
        rdb_session,
        catalog=catalog,
        source_snapshot_id=None,
        entries=[
            LLMCatalogEntryCreate(
                provider=LLMProvider.OPENAI,
                provider_model_identifier="gpt-4o",
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
                runtime_model_identifier="gpt-4o",
                display_name="GPT-4o",
                normalized_capabilities=ModelCapabilities().model_dump(mode="json"),
                supported_execution_options=[],
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                provider_integration_id=None,
                publisher="openai",
                family="gpt",
                source_metadata=None,
                projection_metadata=None,
                hidden_reason=None,
            )
        ],
        diagnostics={"test": True},
    )

    await rdb_session.flush()
    snapshot_count = await rdb_session.scalar(
        sa.select(sa.func.count()).select_from(RDBLLMCatalogSnapshot)
    )
    entry_count = await rdb_session.scalar(
        sa.select(sa.func.count()).select_from(RDBLLMCatalogEntry)
    )

    assert snapshot_id is not None
    assert snapshot_count == 1
    assert entry_count == 1


async def test_partial_catalog_upserts_survive_prepared_statement_reuse(
    rdb_session: AsyncSession,
) -> None:
    """Partial-index upserts must remain inferable after psycopg prepares them."""
    workspace_repository = WorkspaceRepository()
    workspace_result = await workspace_repository.create(
        rdb_session,
        WorkspaceCreate(
            name="Prepared catalog workspace",
            handle="prepared-catalog-workspace",
        ),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await workspace_repository.resolve_id(
        rdb_session, "prepared-catalog-workspace"
    )
    assert workspace_id is not None

    integration = await LLMProviderIntegrationRepository(
        CredentialCipher(Fernet.generate_key().decode())
    ).create(
        rdb_session,
        LLMProviderIntegrationCreate(
            workspace_id=workspace_id,
            provider=LLMProvider.CHATGPT_OAUTH,
            name="Prepared ChatGPT integration",
            secrets=ChatGPTOAuthSecrets(
                access_token="access-token",
                refresh_token="refresh-token",
                expires_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC),
            ),
            config=ChatGPTOAuthConfig(
                connection_method="callback",
                status="connected",
            ),
        ),
    )

    repository = LLMCatalogRepository()
    integration_catalog_ids = {
        (
            await repository.ensure_integration_catalog(
                rdb_session,
                integration_id=integration.id,
                provider=LLMProvider.CHATGPT_OAUTH,
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
                purpose=LLMCatalogPurpose.CONVERSATION,
            )
        ).id
        for _ in range(8)
    }
    system_catalog_ids = {
        (
            await repository.ensure_system_catalog(
                rdb_session,
                provider=LLMProvider.OPENAI,
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
                purpose=LLMCatalogPurpose.CONVERSATION,
            )
        ).id
        for _ in range(8)
    }

    assert len(integration_catalog_ids) == 1
    assert len(system_catalog_ids) == 1


async def test_chatgpt_integration_never_falls_back_to_system_catalog(
    rdb_session: AsyncSession,
) -> None:
    """Do not expose system-projected models to an account-scoped integration."""
    workspace_repository = WorkspaceRepository()
    workspace_result = await workspace_repository.create(
        rdb_session,
        WorkspaceCreate(
            name="ChatGPT fallback workspace",
            handle="chatgpt-fallback-workspace",
        ),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await workspace_repository.resolve_id(
        rdb_session, "chatgpt-fallback-workspace"
    )
    assert workspace_id is not None

    integration = await LLMProviderIntegrationRepository(
        CredentialCipher(Fernet.generate_key().decode())
    ).create(
        rdb_session,
        LLMProviderIntegrationCreate(
            workspace_id=workspace_id,
            provider=LLMProvider.CHATGPT_OAUTH,
            name="ChatGPT Subscription",
            secrets=ChatGPTOAuthSecrets(
                access_token="access-token",
                refresh_token="refresh-token",
                expires_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC),
            ),
            config=ChatGPTOAuthConfig(
                account_id="account-123",
                email="user@example.com",
                plan_type="plus",
                connection_method="callback",
                status="connected",
                connected_at=datetime.datetime(2026, 7, 14, tzinfo=datetime.UTC),
            ),
        ),
    )
    repository = LLMCatalogRepository()
    system_catalog = await repository.ensure_system_catalog(
        rdb_session,
        provider=LLMProvider.CHATGPT_OAUTH,
        lowerer_target=LLMCatalogLowererTarget.LITELLM,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    await repository.replace_current_snapshot(
        rdb_session,
        catalog=system_catalog,
        source_snapshot_id=None,
        entries=[
            LLMCatalogEntryCreate(
                provider=LLMProvider.CHATGPT_OAUTH,
                provider_model_identifier="gpt-system-only",
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
                runtime_model_identifier="chatgpt/gpt-system-only",
                display_name="System-only GPT",
                normalized_capabilities=ModelCapabilities().model_dump(mode="json"),
                supported_execution_options=[],
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                provider_integration_id=None,
                publisher="openai",
                family="gpt",
                source_metadata=None,
                projection_metadata=None,
                hidden_reason=None,
            )
        ],
        diagnostics=None,
    )

    result = await repository.list_entries_by_integration(
        rdb_session,
        integration_id=integration.id,
        workspace_id=workspace_id,
        purpose=LLMCatalogPurpose.CONVERSATION,
        search=None,
        limit=50,
        offset=0,
    )

    assert result is None


async def test_integration_attempt_claim_enforces_running_and_cooldown(
    rdb_session: AsyncSession,
) -> None:
    """Integration attempt claims serialize starts and enforce cooldown."""
    workspace_repository = WorkspaceRepository()
    workspace_result = await workspace_repository.create(
        rdb_session,
        WorkspaceCreate(
            name="Catalog policy workspace",
            handle="catalog-policy-workspace",
        ),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await workspace_repository.resolve_id(
        rdb_session, "catalog-policy-workspace"
    )
    assert workspace_id is not None
    integration = await LLMProviderIntegrationRepository(
        CredentialCipher(Fernet.generate_key().decode())
    ).create(
        rdb_session,
        LLMProviderIntegrationCreate(
            workspace_id=workspace_id,
            provider=LLMProvider.CHATGPT_OAUTH,
            name="Catalog policy ChatGPT integration",
            secrets=ChatGPTOAuthSecrets(
                access_token="access-token",
                refresh_token="refresh-token",
                expires_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC),
            ),
            config=ChatGPTOAuthConfig(
                connection_method="callback",
                status="connected",
            ),
        ),
    )
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_integration_catalog(
        rdb_session,
        integration_id=integration.id,
        provider=integration.provider,
        lowerer_target=LLMCatalogLowererTarget.LITELLM,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    now = datetime.datetime(2026, 7, 16, 12, 0, tzinfo=datetime.UTC)

    first = await repository.begin_integration_attempt(
        rdb_session,
        catalog_id=catalog.id,
        workspace_id=workspace_id,
        source_key="litellm_model_cost",
        started_at=now,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )
    assert isinstance(first, str)

    duplicate = await repository.begin_integration_attempt(
        rdb_session,
        catalog_id=catalog.id,
        workspace_id=workspace_id,
        source_key="litellm_model_cost",
        started_at=now + datetime.timedelta(seconds=1),
        trigger=IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
    )
    assert isinstance(duplicate, IntegrationCatalogSyncPolicyDecision)
    assert duplicate.denial_reason == IntegrationCatalogSyncDenialReason.ALREADY_RUNNING
    assert duplicate.blocking_attempt_id == first

    await repository.mark_attempt_succeeded(
        rdb_session,
        attempt_id=first,
        finished_at=now + datetime.timedelta(seconds=2),
        produced_snapshot_id=None,
        fetched_count=0,
        matched_count=0,
        skipped_count=0,
        hidden_count=0,
        diagnostics={"trigger": IntegrationCatalogSyncTrigger.CREATE.value},
    )
    throttled = await repository.begin_integration_attempt(
        rdb_session,
        catalog_id=catalog.id,
        workspace_id=workspace_id,
        source_key="litellm_model_cost",
        started_at=now + datetime.timedelta(seconds=10),
        trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
    )
    assert isinstance(throttled, IntegrationCatalogSyncPolicyDecision)
    assert throttled.denial_reason == IntegrationCatalogSyncDenialReason.THROTTLED

    after_cooldown = await repository.begin_integration_attempt(
        rdb_session,
        catalog_id=catalog.id,
        workspace_id=workspace_id,
        source_key="litellm_model_cost",
        started_at=now + datetime.timedelta(seconds=31),
        trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
    )
    assert isinstance(after_cooldown, str)
    current_attempt_id = await repository.lock_catalog_for_attempt_completion(
        rdb_session,
        catalog_id=catalog.id,
    )
    assert current_attempt_id == after_cooldown
    assert current_attempt_id != first


async def test_catalog_identity_is_purpose_aware(
    rdb_session: AsyncSession,
) -> None:
    """The same integration and lowerer target may own both catalog purposes."""
    (
        workspace_id,
        _integration_repository,
        integration_id,
    ) = await _create_openai_integration(
        rdb_session,
        handle="purpose-aware-catalog",
    )
    repository = LLMCatalogRepository()

    conversation = await repository.ensure_integration_catalog(
        rdb_session,
        integration_id=integration_id,
        provider=LLMProvider.OPENAI,
        lowerer_target=LLMCatalogLowererTarget.LITELLM,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    image = await repository.ensure_integration_catalog(
        rdb_session,
        integration_id=integration_id,
        provider=LLMProvider.OPENAI,
        lowerer_target=LLMCatalogLowererTarget.LITELLM,
        purpose=LLMCatalogPurpose.IMAGE_GENERATION,
    )

    assert conversation.id != image.id
    assert (
        await repository.get_by_integration(
            rdb_session,
            integration_id=integration_id,
            workspace_id=workspace_id,
            purpose=LLMCatalogPurpose.CONVERSATION,
        )
    ) == conversation
    assert (
        await repository.get_by_integration(
            rdb_session,
            integration_id=integration_id,
            workspace_id=workspace_id,
            purpose=LLMCatalogPurpose.IMAGE_GENERATION,
        )
    ) == image


async def test_image_catalog_fences_generation_and_preserves_last_good(
    rdb_session: AsyncSession,
) -> None:
    """Failed or superseded refreshes keep the prior snapshot diagnostic state."""
    (
        workspace_id,
        integration_repository,
        integration_id,
    ) = await _create_openai_integration(
        rdb_session,
        handle="image-generation-fencing",
    )
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_integration_catalog(
        rdb_session,
        integration_id=integration_id,
        provider=LLMProvider.OPENAI,
        lowerer_target=LLMCatalogLowererTarget.LITELLM,
        purpose=LLMCatalogPurpose.IMAGE_GENERATION,
    )
    started_at = datetime.datetime.now(datetime.UTC)
    first_attempt = await repository.begin_integration_attempt(
        rdb_session,
        catalog_id=catalog.id,
        workspace_id=workspace_id,
        source_key="openai_models_list:image_generation",
        started_at=started_at,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )
    assert isinstance(first_attempt, str)
    first_publication = await repository.replace_current_image_generation_snapshot(
        rdb_session,
        catalog=catalog,
        attempt_id=first_attempt,
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
    assert first_publication.snapshot_id is not None
    await repository.mark_attempt_succeeded(
        rdb_session,
        attempt_id=first_attempt,
        finished_at=started_at + datetime.timedelta(seconds=1),
        produced_snapshot_id=first_publication.snapshot_id,
        fetched_count=1,
        matched_count=1,
        skipped_count=0,
        hidden_count=0,
        diagnostics={"catalog_purpose": "image_generation"},
    )

    update_result = await integration_repository.update_by_id(
        rdb_session,
        integration_id,
        LLMProviderIntegrationUpdate(
            secrets=ApiKeySecrets(api_key="sk-updated"),
        ),
    )
    assert isinstance(update_result, Success)
    assert update_result.value.catalog_configuration_version == 2
    page = await repository.list_image_generation_entries_by_integration(
        rdb_session,
        integration_id=integration_id,
        workspace_id=workspace_id,
    )
    assert page is not None
    assert page.catalog.current_snapshot_id == first_publication.snapshot_id
    assert page.snapshot_catalog_configuration_version == 1
    assert page.current_integration_catalog_configuration_version == 2
    assert [entry.provider_model_identifier for entry in page.entries] == [
        "gpt-image-2.5-flare"
    ]
    assert (
        await repository.get_selectable_image_generation_entry(
            rdb_session,
            integration_id=integration_id,
            workspace_id=workspace_id,
            model_identifier="gpt-image-2.5-flare",
        )
        is None
    )

    second_attempt = await repository.begin_integration_attempt(
        rdb_session,
        catalog_id=catalog.id,
        workspace_id=workspace_id,
        source_key="openai_models_list:image_generation",
        started_at=started_at + datetime.timedelta(seconds=31),
        trigger=IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
    )
    assert isinstance(second_attempt, str)
    second_update = await integration_repository.update_by_id(
        rdb_session,
        integration_id,
        LLMProviderIntegrationUpdate(
            secrets=ApiKeySecrets(api_key="sk-newer"),
        ),
    )
    assert isinstance(second_update, Success)
    assert second_update.value.catalog_configuration_version == 3
    superseded = await repository.replace_current_image_generation_snapshot(
        rdb_session,
        catalog=catalog,
        attempt_id=second_attempt,
        entries=[],
        diagnostics=None,
    )
    assert superseded.snapshot_id is None
    assert superseded.current_catalog_configuration_version == 3

    preserved = await repository.list_image_generation_entries_by_integration(
        rdb_session,
        integration_id=integration_id,
        workspace_id=workspace_id,
    )
    assert preserved is not None
    assert preserved.catalog.current_snapshot_id == first_publication.snapshot_id
    assert [entry.provider_model_identifier for entry in preserved.entries] == [
        "gpt-image-2.5-flare"
    ]
