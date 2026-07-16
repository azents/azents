"""LLM catalog repository tests."""

import datetime

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import ChatGPTOAuthConfig, ChatGPTOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMCatalogLowererTarget,
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
from azents.repos.llm_catalog.data import LLMCatalogEntryCreate
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

pytestmark = pytest.mark.asyncio


async def test_replace_current_snapshot_persists_snapshot_before_entries(
    rdb_session: AsyncSession,
) -> None:
    """Snapshot replacement should satisfy entry snapshot FK ordering."""
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        lowerer_target=LLMCatalogLowererTarget.LITELLM,
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
