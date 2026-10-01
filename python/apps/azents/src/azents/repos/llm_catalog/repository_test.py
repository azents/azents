"""LLM catalog repository tests."""

import datetime
from typing import NamedTuple

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
from azents.rdb.models.llm_catalog import (
    RDBLLMCatalog,
    RDBLLMCatalogEntry,
    RDBLLMCatalogSnapshot,
    RDBLLMCatalogSyncAttempt,
)
from azents.rdb.models.model_metadata_source import (
    RDBModelMetadataSource,
    RDBModelMetadataSourceSnapshot,
)
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    CatalogProjectionProvenance,
    CatalogSyncAlreadyRunning,
    ImageGenerationCatalogEntryCreate,
    IntegrationCatalogSyncClaim,
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


class _OpenAIIntegrationFixture(NamedTuple):
    """OpenAI integration repository test fixture."""

    workspace_id: str
    repository: LLMProviderIntegrationRepository
    integration_id: str


async def _create_openai_integration(
    rdb_session: AsyncSession,
    *,
    handle: str,
) -> _OpenAIIntegrationFixture:
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
    return _OpenAIIntegrationFixture(
        workspace_id=workspace_id,
        repository=integration_repository,
        integration_id=integration.id,
    )


async def test_replace_current_snapshot_persists_snapshot_before_entries(
    rdb_session: AsyncSession,
) -> None:
    """Snapshot replacement should satisfy entry snapshot FK ordering."""
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
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


async def test_system_attempt_reclaims_an_abandoned_running_lease(
    rdb_session: AsyncSession,
) -> None:
    """A process-lost system refresh cannot wedge later scheduler or Admin runs."""
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    started_at = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
    first = await repository.begin_attempt(
        rdb_session,
        catalog_id=catalog.id,
        source_key="genai_prices",
        started_at=started_at,
    )
    assert isinstance(first, str)

    still_running = await repository.begin_attempt(
        rdb_session,
        catalog_id=catalog.id,
        source_key="genai_prices",
        started_at=started_at + datetime.timedelta(minutes=4, seconds=59),
    )
    assert isinstance(still_running, CatalogSyncAlreadyRunning)
    assert still_running.attempt_id == first

    reclaimed = await repository.begin_attempt(
        rdb_session,
        catalog_id=catalog.id,
        source_key="genai_prices",
        started_at=started_at + datetime.timedelta(minutes=5),
    )
    assert isinstance(reclaimed, str)
    assert reclaimed != first
    abandoned = await rdb_session.get(RDBLLMCatalogSyncAttempt, first)
    assert abandoned is not None
    assert abandoned.failure_code == "SystemCatalogSyncRunningTimeout"


async def test_candidate_snapshot_is_complete_and_does_not_publish(
    rdb_session: AsyncSession,
) -> None:
    """Shadow projection remains non-current and is reused by fingerprint."""
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    entry = LLMCatalogEntryCreate(
        provider=LLMProvider.OPENAI,
        provider_model_identifier="gpt-shadow",
        display_name="GPT Shadow",
        normalized_capabilities=ModelCapabilities().model_dump(mode="json"),
        supported_execution_options=[],
        lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
        visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
        provider_integration_id=None,
        publisher="openai",
        family="gpt",
        source_metadata={"source_kind": "genai_prices"},
        projection_metadata={"resolver_revision": "1"},
        hidden_reason=None,
    )
    source_id = "s" * 32
    rdb_session.add(
        RDBModelMetadataSource(
            source_key="genai_prices",
            current_snapshot_id=source_id,
            latest_attempt_id=None,
        )
    )
    rdb_session.add(
        RDBModelMetadataSourceSnapshot(
            id=source_id,
            source_key="genai_prices",
            source_kind="genai_prices",
            source_schema_version="1",
            source_url="https://metadata.example/data.json",
            source_hash="b" * 64,
            producer_name="genai-prices",
            producer_version="0.1.9",
            provider_count=0,
            model_count=0,
            payload={"schema_version": "1", "providers": []},
        )
    )
    await rdb_session.flush()
    provenance = CatalogProjectionProvenance(
        metadata_source_snapshot_id=source_id,
        projection_schema_version="1",
        runtime_profile_resolver_revision="1",
        pydantic_ai_version="2.52.0",
        genai_prices_version="0.1.9",
        projection_fingerprint="a" * 64,
    )

    candidate_id = await repository.create_candidate_snapshot(
        rdb_session,
        catalog=catalog,
        entries=[entry],
        diagnostics={"shadow": True},
        provenance=provenance,
        catalog_configuration_version=None,
    )
    reused_id = await repository.create_candidate_snapshot(
        rdb_session,
        catalog=catalog,
        entries=[entry],
        diagnostics={"shadow": True},
        provenance=provenance,
        catalog_configuration_version=None,
    )

    catalog_row = await rdb_session.get(RDBLLMCatalog, catalog.id)
    snapshot = await rdb_session.get(RDBLLMCatalogSnapshot, candidate_id)
    assert reused_id == candidate_id
    assert catalog_row is not None
    assert catalog_row.current_snapshot_id is None
    assert catalog_row.rollback_snapshot_id is None
    assert snapshot is not None
    assert snapshot.metadata_source_snapshot_id == source_id
    assert snapshot.projection_fingerprint == "a" * 64


async def test_ordinary_publication_preserves_pinned_rollback_snapshot(
    rdb_session: AsyncSession,
) -> None:
    """A later publication cannot delete the explicit rollback snapshot."""
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    first_id = await repository.replace_current_snapshot(
        rdb_session,
        catalog=catalog,
        source_snapshot_id=None,
        entries=[],
        diagnostics={"generation": 1},
    )
    stale_catalog = await repository.get_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    assert stale_catalog is not None
    assert stale_catalog.rollback_snapshot_id is None
    catalog_row = await rdb_session.get(RDBLLMCatalog, catalog.id)
    assert catalog_row is not None
    catalog_row.rollback_snapshot_id = first_id
    await rdb_session.flush()

    second_id = await repository.replace_current_snapshot(
        rdb_session,
        catalog=stale_catalog,
        source_snapshot_id=None,
        entries=[],
        diagnostics={"generation": 2},
    )

    assert second_id != first_id
    assert await rdb_session.get(RDBLLMCatalogSnapshot, first_id) is not None
    assert await rdb_session.get(RDBLLMCatalogSnapshot, second_id) is not None


async def test_cutover_pins_exact_current_and_coordinated_rollback_restores_it(
    rdb_session: AsyncSession,
) -> None:
    """Cutover is atomic, idempotent, and reversible before cleanup."""
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    legacy_snapshot_id = await repository.replace_current_snapshot(
        rdb_session,
        catalog=catalog,
        source_snapshot_id=None,
        entries=[],
        diagnostics={"authority": "legacy"},
    )
    source_id = "m" * 32
    rdb_session.add(
        RDBModelMetadataSource(
            source_key="genai_prices",
            current_snapshot_id=source_id,
            latest_attempt_id=None,
        )
    )
    rdb_session.add(
        RDBModelMetadataSourceSnapshot(
            id=source_id,
            source_key="genai_prices",
            source_kind="genai_prices",
            source_schema_version="1",
            source_url="https://metadata.example/data.json",
            source_hash="c" * 64,
            producer_name="genai-prices",
            producer_version="0.1.9",
            provider_count=1,
            model_count=1,
            payload={"schema_version": "1", "providers": []},
        )
    )
    await rdb_session.flush()
    refreshed = await repository.get_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    assert refreshed is not None
    candidate_id = await repository.create_candidate_snapshot(
        rdb_session,
        catalog=refreshed,
        entries=[],
        diagnostics={"shadow": True},
        provenance=CatalogProjectionProvenance(
            metadata_source_snapshot_id=source_id,
            projection_schema_version="1",
            runtime_profile_resolver_revision="2",
            pydantic_ai_version="2.52.0",
            genai_prices_version="0.1.9",
            projection_fingerprint="f" * 64,
        ),
        catalog_configuration_version=None,
    )

    published = await repository.publish_cutover_candidate(
        rdb_session,
        catalog_id=catalog.id,
        candidate_snapshot_id=candidate_id,
        expected_metadata_source_key="genai_prices",
        expected_metadata_source_snapshot_id=source_id,
        expected_projection_fingerprint="f" * 64,
    )
    repeated = await repository.publish_cutover_candidate(
        rdb_session,
        catalog_id=catalog.id,
        candidate_snapshot_id=candidate_id,
        expected_metadata_source_key="genai_prices",
        expected_metadata_source_snapshot_id=source_id,
        expected_projection_fingerprint="f" * 64,
    )

    catalog_row = await rdb_session.get(RDBLLMCatalog, catalog.id)
    assert catalog_row is not None
    assert published == candidate_id
    assert repeated == candidate_id
    assert catalog_row.current_snapshot_id == candidate_id
    assert catalog_row.rollback_snapshot_id == legacy_snapshot_id
    assert await rdb_session.get(RDBLLMCatalogSnapshot, legacy_snapshot_id) is not None

    restored = await repository.rollback_cutover(
        rdb_session,
        catalog_id=catalog.id,
    )

    assert restored == legacy_snapshot_id
    assert catalog_row.current_snapshot_id == legacy_snapshot_id
    assert catalog_row.rollback_snapshot_id is None
    assert await rdb_session.get(RDBLLMCatalogSnapshot, candidate_id) is None


async def test_cutover_rejects_candidate_provenance_without_changing_pointers(
    rdb_session: AsyncSession,
) -> None:
    """A stale readiness fingerprint cannot publish or create a rollback pin."""
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    legacy_snapshot_id = await repository.replace_current_snapshot(
        rdb_session,
        catalog=catalog,
        source_snapshot_id=None,
        entries=[],
        diagnostics={"authority": "legacy"},
    )
    source_id = "n" * 32
    rdb_session.add(
        RDBModelMetadataSource(
            source_key="genai_prices",
            current_snapshot_id=source_id,
            latest_attempt_id=None,
        )
    )
    rdb_session.add(
        RDBModelMetadataSourceSnapshot(
            id=source_id,
            source_key="genai_prices",
            source_kind="genai_prices",
            source_schema_version="1",
            source_url="https://metadata.example/data.json",
            source_hash="d" * 64,
            producer_name="genai-prices",
            producer_version="0.1.9",
            provider_count=1,
            model_count=1,
            payload={"schema_version": "1", "providers": []},
        )
    )
    await rdb_session.flush()
    refreshed = await repository.get_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    assert refreshed is not None
    candidate_id = await repository.create_candidate_snapshot(
        rdb_session,
        catalog=refreshed,
        entries=[],
        diagnostics={"shadow": True},
        provenance=CatalogProjectionProvenance(
            metadata_source_snapshot_id=source_id,
            projection_schema_version="1",
            runtime_profile_resolver_revision="2",
            pydantic_ai_version="2.52.0",
            genai_prices_version="0.1.9",
            projection_fingerprint="e" * 64,
        ),
        catalog_configuration_version=None,
    )

    with pytest.raises(RuntimeError, match="provenance changed"):
        await repository.publish_cutover_candidate(
            rdb_session,
            catalog_id=catalog.id,
            candidate_snapshot_id=candidate_id,
            expected_metadata_source_key="genai_prices",
            expected_metadata_source_snapshot_id=source_id,
            expected_projection_fingerprint="x" * 64,
        )

    catalog_row = await rdb_session.get(RDBLLMCatalog, catalog.id)
    assert catalog_row is not None
    assert catalog_row.current_snapshot_id == legacy_snapshot_id
    assert catalog_row.rollback_snapshot_id is None


async def test_system_publication_refreshes_without_moving_rollback_pin(
    rdb_session: AsyncSession,
) -> None:
    """Later generic refreshes retain the exact original legacy rollback pin."""
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    legacy_snapshot_id = await repository.replace_current_snapshot(
        rdb_session,
        catalog=catalog,
        source_snapshot_id=None,
        entries=[],
        diagnostics={"authority": "legacy"},
    )
    authority = RDBModelMetadataSource(
        source_key="genai_prices",
        current_snapshot_id=None,
        latest_attempt_id=None,
    )
    rdb_session.add(authority)
    source_ids = ["1" * 32, "2" * 32]
    for index, source_id in enumerate(source_ids, start=1):
        rdb_session.add(
            RDBModelMetadataSourceSnapshot(
                id=source_id,
                source_key="genai_prices",
                source_kind="genai_prices",
                source_schema_version="1",
                source_url="https://metadata.example/data.json",
                source_hash=str(index) * 64,
                producer_name="genai-prices",
                producer_version="0.1.9",
                provider_count=1,
                model_count=1,
                payload={"schema_version": "1", "providers": []},
            )
        )
    authority.current_snapshot_id = source_ids[0]
    await rdb_session.flush()

    current_catalog = await repository.get_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    assert current_catalog is not None
    first_candidate = await repository.create_candidate_snapshot(
        rdb_session,
        catalog=current_catalog,
        entries=[],
        diagnostics=None,
        provenance=CatalogProjectionProvenance(
            metadata_source_snapshot_id=source_ids[0],
            projection_schema_version="1",
            runtime_profile_resolver_revision="1",
            pydantic_ai_version="2.52.0",
            genai_prices_version="0.1.9",
            projection_fingerprint="1" * 64,
        ),
        catalog_configuration_version=None,
    )
    await repository.publish_cutover_candidate(
        rdb_session,
        catalog_id=catalog.id,
        candidate_snapshot_id=first_candidate,
        expected_metadata_source_key="genai_prices",
        expected_metadata_source_snapshot_id=source_ids[0],
        expected_projection_fingerprint="1" * 64,
    )

    authority.current_snapshot_id = source_ids[1]
    await rdb_session.flush()
    refreshed_catalog = await repository.get_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    assert refreshed_catalog is not None
    second_candidate = await repository.create_candidate_snapshot(
        rdb_session,
        catalog=refreshed_catalog,
        entries=[],
        diagnostics=None,
        provenance=CatalogProjectionProvenance(
            metadata_source_snapshot_id=source_ids[1],
            projection_schema_version="1",
            runtime_profile_resolver_revision="1",
            pydantic_ai_version="2.52.0",
            genai_prices_version="0.1.9",
            projection_fingerprint="2" * 64,
        ),
        catalog_configuration_version=None,
    )
    await repository.publish_cutover_candidate(
        rdb_session,
        catalog_id=catalog.id,
        candidate_snapshot_id=second_candidate,
        expected_metadata_source_key="genai_prices",
        expected_metadata_source_snapshot_id=source_ids[1],
        expected_projection_fingerprint="2" * 64,
    )

    catalog_row = await rdb_session.get(RDBLLMCatalog, catalog.id)
    assert catalog_row is not None
    assert catalog_row.current_snapshot_id == second_candidate
    assert catalog_row.rollback_snapshot_id == legacy_snapshot_id
    assert await rdb_session.get(RDBLLMCatalogSnapshot, legacy_snapshot_id) is not None
    assert await rdb_session.get(RDBLLMCatalogSnapshot, first_candidate) is None


async def test_system_publication_fences_current_source_authority(
    rdb_session: AsyncSession,
) -> None:
    """A candidate for an obsolete generic source cannot change pointers."""
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    legacy_snapshot_id = await repository.replace_current_snapshot(
        rdb_session,
        catalog=catalog,
        source_snapshot_id=None,
        entries=[],
        diagnostics={"authority": "legacy"},
    )
    source_id = "3" * 32
    current_source_id = "4" * 32
    rdb_session.add(
        RDBModelMetadataSource(
            source_key="genai_prices",
            current_snapshot_id=current_source_id,
            latest_attempt_id=None,
        )
    )
    for snapshot_id, source_hash in (
        (source_id, "3" * 64),
        (current_source_id, "4" * 64),
    ):
        rdb_session.add(
            RDBModelMetadataSourceSnapshot(
                id=snapshot_id,
                source_key="genai_prices",
                source_kind="genai_prices",
                source_schema_version="1",
                source_url="https://metadata.example/data.json",
                source_hash=source_hash,
                producer_name="genai-prices",
                producer_version="0.1.9",
                provider_count=1,
                model_count=1,
                payload={"schema_version": "1", "providers": []},
            )
        )
    await rdb_session.flush()
    candidate = await repository.create_candidate_snapshot(
        rdb_session,
        catalog=catalog,
        entries=[],
        diagnostics=None,
        provenance=CatalogProjectionProvenance(
            metadata_source_snapshot_id=source_id,
            projection_schema_version="1",
            runtime_profile_resolver_revision="1",
            pydantic_ai_version="2.52.0",
            genai_prices_version="0.1.9",
            projection_fingerprint="3" * 64,
        ),
        catalog_configuration_version=None,
    )

    with pytest.raises(RuntimeError, match="metadata source changed"):
        await repository.publish_cutover_candidate(
            rdb_session,
            catalog_id=catalog.id,
            candidate_snapshot_id=candidate,
            expected_metadata_source_key="genai_prices",
            expected_metadata_source_snapshot_id=source_id,
            expected_projection_fingerprint="3" * 64,
        )

    catalog_row = await rdb_session.get(RDBLLMCatalog, catalog.id)
    assert catalog_row is not None
    assert catalog_row.current_snapshot_id == legacy_snapshot_id
    assert catalog_row.rollback_snapshot_id is None


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
    assert isinstance(first, IntegrationCatalogSyncClaim)

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
    assert duplicate.blocking_attempt_id == first.attempt_id

    await repository.mark_attempt_succeeded(
        rdb_session,
        attempt_id=first.attempt_id,
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
    assert isinstance(after_cooldown, IntegrationCatalogSyncClaim)
    current_attempt_id = await repository.lock_catalog_for_attempt_completion(
        rdb_session,
        catalog_id=catalog.id,
    )
    assert current_attempt_id == after_cooldown.attempt_id
    assert current_attempt_id != first.attempt_id


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
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    image = await repository.ensure_integration_catalog(
        rdb_session,
        integration_id=integration_id,
        provider=LLMProvider.OPENAI,
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
    assert isinstance(first_attempt, IntegrationCatalogSyncClaim)
    first_publication = await repository.replace_current_image_generation_snapshot(
        rdb_session,
        catalog=catalog,
        attempt_id=first_attempt.attempt_id,
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
        attempt_id=first_attempt.attempt_id,
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
    assert isinstance(second_attempt, IntegrationCatalogSyncClaim)
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
        attempt_id=second_attempt.attempt_id,
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
