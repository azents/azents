"""Current catalog replacement, ownership and purpose-specific authority."""

import dataclasses
import datetime
from typing import NamedTuple

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import ApiKeySecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMCatalogPurpose,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog import ModelCapabilities
from azents.core.llm_catalog_sync import (
    CatalogProjectionVersion,
    IntegrationCatalogSyncDenialReason,
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncTrigger,
)
from azents.core.model_pricing import normalize_model_pricing
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.llm_catalog import RDBLLMCatalog, RDBLLMCatalogEntry
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    ImageGenerationCatalogEntryCreate,
    IntegrationCatalogSyncClaim,
    LLMCatalog,
    LLMCatalogEntryCreate,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationCreate
from azents.repos.workspace import WorkspaceRepository

pytestmark = pytest.mark.asyncio
_NOW = datetime.datetime(2026, 10, 3, tzinfo=datetime.UTC)


class _Fixture(NamedTuple):
    workspace_id: str
    integration_id: str
    integration_repository: LLMProviderIntegrationRepository


async def _integration(
    session: AsyncSession, *, handle: str, provider: LLMProvider = LLMProvider.XAI
) -> _Fixture:
    workspaces = WorkspaceRepository()
    result = await workspaces.create(
        session, WorkspaceCreate(name=handle, handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await workspaces.resolve_id(session, handle)
    assert workspace_id is not None
    integrations = LLMProviderIntegrationRepository(
        CredentialCipher(Fernet.generate_key().decode())
    )
    integration = await integrations.create(
        session,
        LLMProviderIntegrationCreate(
            workspace_id=workspace_id,
            provider=provider,
            name="Catalog test",
            secrets=ApiKeySecrets(api_key="test-key"),
        ),
    )
    return _Fixture(
        workspace_id=workspace_id,
        integration_id=integration.id,
        integration_repository=integrations,
    )


def _entry(
    *,
    integration_id: str,
    identifier: str,
    provider: LLMProvider = LLMProvider.XAI,
    visibility: LLMCatalogEntryVisibility = LLMCatalogEntryVisibility.SELECTABLE,
) -> LLMCatalogEntryCreate:
    return LLMCatalogEntryCreate(
        provider=provider,
        provider_model_identifier=identifier,
        display_name=identifier,
        normalized_capabilities=ModelCapabilities().model_dump(mode="json"),
        supported_execution_options=[],
        lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
        visibility_status=visibility,
        provider_integration_id=integration_id,
        publisher=None,
        family=None,
        source_metadata=None,
        projection_metadata=None,
        hidden_reason=None,
        pricing=normalize_model_pricing(
            source_key=None, source_model=None, collected_at=None
        ),
    )


def _image(
    *, integration_id: str, identifier: str
) -> ImageGenerationCatalogEntryCreate:
    return ImageGenerationCatalogEntryCreate(
        provider=LLMProvider.OPENAI,
        provider_model_identifier=identifier,
        display_name=identifier,
        description="Reviewed fixture model.",
        recommendation_rank=1,
        lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
        visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
        provider_integration_id=integration_id,
        source_metadata=None,
        projection_metadata=None,
        hidden_reason=None,
    )


async def _publish(
    session: AsyncSession,
    repository: LLMCatalogRepository,
    *,
    fixture: _Fixture,
    catalog: LLMCatalog,
    entries: list[LLMCatalogEntryCreate],
    finished_at: datetime.datetime,
) -> IntegrationCatalogSyncClaim:
    claim = await repository.begin_integration_sync(
        session,
        catalog_id=catalog.id,
        workspace_id=fixture.workspace_id,
        started_at=finished_at,
        trigger=IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
        required_projection_version=None,
    )
    assert isinstance(claim, IntegrationCatalogSyncClaim)
    owner = await repository.lock_catalog(session, catalog_id=catalog.id)
    await repository.replace_current_entries(
        session, owner=owner, entries=entries, diagnostics=None, finished_at=finished_at
    )
    await repository.complete_sync(
        session,
        catalog_id=catalog.id,
        work_token=claim.work_token,
        finished_at=finished_at,
        fetched_count=len(entries),
        matched_count=len(entries),
        skipped_count=0,
        hidden_count=owner.hidden_count,
        diagnostics=None,
    )
    return claim


async def test_current_upsert_preserves_ids_removes_absent_and_advances_refresh(
    rdb_session: AsyncSession,
) -> None:
    fixture = await _integration(rdb_session, handle="catalog-current")
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_integration_catalog(
        rdb_session,
        integration_id=fixture.integration_id,
        provider=LLMProvider.XAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    entries = [
        _entry(integration_id=fixture.integration_id, identifier="literal"),
        _entry(integration_id=fixture.integration_id, identifier="removed"),
    ]
    await _publish(
        rdb_session,
        repository,
        fixture=fixture,
        catalog=catalog,
        entries=entries,
        finished_at=_NOW,
    )
    first = await repository.get_selectable_entry_by_integration_model(
        rdb_session,
        integration_id=fixture.integration_id,
        workspace_id=fixture.workspace_id,
        model_identifier="literal",
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    assert first is not None
    newer = _NOW + datetime.timedelta(seconds=1)
    await _publish(
        rdb_session,
        repository,
        fixture=fixture,
        catalog=catalog,
        entries=[dataclasses.replace(entries[0], display_name="Updated literal")],
        finished_at=newer,
    )
    current = await repository.get_selectable_entry_by_integration_model(
        rdb_session,
        integration_id=fixture.integration_id,
        workspace_id=fixture.workspace_id,
        model_identifier="literal",
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    assert current is not None
    assert current.entry.id == first.entry.id
    assert current.entry.created_at == first.entry.created_at
    assert current.entry.updated_at == newer
    assert current.entry.display_name == "Updated literal"
    assert current.catalog.last_success_at == newer
    count = await rdb_session.scalar(
        sa.select(sa.func.count())
        .select_from(RDBLLMCatalogEntry)
        .where(RDBLLMCatalogEntry.catalog_id == catalog.id)
    )
    assert count == 1
    assert current.catalog.entry_count == 1
    assert current.catalog.sync_status is not None
    assert current.catalog.sync_status.work_token is None


async def test_failed_refresh_does_not_gate_current_conversation_selection(
    rdb_session: AsyncSession,
) -> None:
    fixture = await _integration(rdb_session, handle="catalog-stale-readable")
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_integration_catalog(
        rdb_session,
        integration_id=fixture.integration_id,
        provider=LLMProvider.XAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    await _publish(
        rdb_session,
        repository,
        fixture=fixture,
        catalog=catalog,
        entries=[_entry(integration_id=fixture.integration_id, identifier="literal")],
        finished_at=_NOW,
    )
    claim = await repository.begin_integration_sync(
        rdb_session,
        catalog_id=catalog.id,
        workspace_id=fixture.workspace_id,
        started_at=_NOW + datetime.timedelta(hours=1),
        trigger=IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
        required_projection_version=None,
    )
    assert isinstance(claim, IntegrationCatalogSyncClaim)
    await repository.fail_sync(
        rdb_session,
        catalog_id=catalog.id,
        work_token=claim.work_token,
        finished_at=_NOW + datetime.timedelta(hours=1),
        failure_code="ListingFailed",
        failure_message="Listing failed.",
        action_hint=None,
        diagnostics={"automatic_retry_blocked": True},
    )
    selected = await repository.get_selectable_entry_by_integration_model(
        rdb_session,
        integration_id=fixture.integration_id,
        workspace_id=fixture.workspace_id,
        model_identifier="literal",
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    assert selected is not None
    assert selected.catalog.last_success_at == _NOW
    assert selected.catalog.image_usable is None
    assert selected.catalog.sync_status is not None
    assert selected.catalog.sync_status.status.value == "failed"


async def test_superseded_failure_does_not_mutate_new_work(
    rdb_session: AsyncSession,
) -> None:
    fixture = await _integration(rdb_session, handle="catalog-work-ownership")
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_integration_catalog(
        rdb_session,
        integration_id=fixture.integration_id,
        provider=LLMProvider.XAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    first = await repository.begin_integration_sync(
        rdb_session,
        catalog_id=catalog.id,
        workspace_id=fixture.workspace_id,
        started_at=_NOW,
        trigger=IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
        required_projection_version=None,
    )
    assert isinstance(first, IntegrationCatalogSyncClaim)
    second = await repository.begin_integration_sync(
        rdb_session,
        catalog_id=catalog.id,
        workspace_id=fixture.workspace_id,
        started_at=_NOW + datetime.timedelta(minutes=16),
        trigger=IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
        required_projection_version=None,
    )
    assert isinstance(second, IntegrationCatalogSyncClaim)
    assert not await repository.fail_sync(
        rdb_session,
        catalog_id=catalog.id,
        work_token=first.work_token,
        finished_at=_NOW,
        failure_code="OldFailed",
        failure_message="Old worker failed.",
        action_hint=None,
        diagnostics=None,
    )
    status = await repository.get_sync_status(rdb_session, catalog=catalog)
    assert status is not None
    assert status.work_token == second.work_token
    assert status.status.value == "running"


async def test_visibility_workspace_and_literal_model_predicates_survive(
    rdb_session: AsyncSession,
) -> None:
    fixture = await _integration(rdb_session, handle="catalog-selectable")
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_integration_catalog(
        rdb_session,
        integration_id=fixture.integration_id,
        provider=LLMProvider.XAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    await _publish(
        rdb_session,
        repository,
        fixture=fixture,
        catalog=catalog,
        entries=[
            _entry(integration_id=fixture.integration_id, identifier="literal"),
            _entry(
                integration_id=fixture.integration_id,
                identifier="hidden",
                visibility=LLMCatalogEntryVisibility.HIDDEN,
            ),
        ],
        finished_at=_NOW,
    )
    for workspace_id, identifier in [
        (fixture.workspace_id, "hidden"),
        (fixture.workspace_id, "xai/literal"),
        ("other-workspace", "literal"),
    ]:
        assert (
            await repository.get_selectable_entry_by_integration_model(
                rdb_session,
                integration_id=fixture.integration_id,
                workspace_id=workspace_id,
                model_identifier=identifier,
                purpose=LLMCatalogPurpose.CONVERSATION,
            )
            is None
        )
    page = await repository.list_entries_by_integration(
        rdb_session,
        integration_id=fixture.integration_id,
        workspace_id=fixture.workspace_id,
        purpose=LLMCatalogPurpose.CONVERSATION,
        search=None,
        limit=20,
        offset=0,
    )
    assert page is not None
    assert page.total == 1
    assert page.catalog.visible_count == 1
    assert page.catalog.hidden_count == 1


async def test_image_credential_change_invalidates_only_image_usability(
    rdb_session: AsyncSession,
) -> None:
    fixture = await _integration(
        rdb_session, handle="catalog-image-authority", provider=LLMProvider.OPENAI
    )
    repository = LLMCatalogRepository()
    conversation = await repository.ensure_integration_catalog(
        rdb_session,
        integration_id=fixture.integration_id,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    await _publish(
        rdb_session,
        repository,
        fixture=fixture,
        catalog=conversation,
        entries=[
            _entry(
                integration_id=fixture.integration_id,
                identifier="literal",
                provider=LLMProvider.OPENAI,
            )
        ],
        finished_at=_NOW,
    )
    image = await repository.ensure_integration_catalog(
        rdb_session,
        integration_id=fixture.integration_id,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.IMAGE_GENERATION,
    )
    owner = await repository.lock_catalog(rdb_session, catalog_id=image.id)
    await repository.replace_current_image_entries(
        rdb_session,
        owner=owner,
        entries=[
            _image(
                integration_id=fixture.integration_id, identifier="gpt-image-2.5-flare"
            )
        ],
        diagnostics=None,
        finished_at=_NOW,
    )
    selected_image = await repository.get_selectable_image_generation_entry(
        rdb_session,
        integration_id=fixture.integration_id,
        workspace_id=fixture.workspace_id,
        model_identifier="gpt-image-2.5-flare",
    )
    assert selected_image is not None
    updated = await fixture.integration_repository.update_by_id(
        rdb_session,
        fixture.integration_id,
        {"secrets": ApiKeySecrets(api_key="replacement-key")},
    )
    assert isinstance(updated, Success)
    assert (
        await repository.get_selectable_image_generation_entry(
            rdb_session,
            integration_id=fixture.integration_id,
            workspace_id=fixture.workspace_id,
            model_identifier="gpt-image-2.5-flare",
        )
        is None
    )
    page = await repository.list_image_generation_entries_by_integration(
        rdb_session,
        integration_id=fixture.integration_id,
        workspace_id=fixture.workspace_id,
    )
    assert page is not None
    assert page.catalog.image_usable is False
    assert page.catalog.last_success_at == _NOW
    assert len(page.entries) == 1
    disabled = await fixture.integration_repository.update_by_id(
        rdb_session, fixture.integration_id, {"enabled": False}
    )
    assert isinstance(disabled, Success)
    assert (
        await repository.get_selectable_image_generation_entry(
            rdb_session,
            integration_id=fixture.integration_id,
            workspace_id=fixture.workspace_id,
            model_identifier="gpt-image-2.5-flare",
        )
        is None
    )
    assert (
        await repository.get_selectable_entry_by_integration_model(
            rdb_session,
            integration_id=fixture.integration_id,
            workspace_id=fixture.workspace_id,
            model_identifier="literal",
            purpose=LLMCatalogPurpose.CONVERSATION,
        )
        is not None
    )


@pytest.mark.parametrize(
    ("version", "stale"),
    [
        (CatalogProjectionVersion("2", "4"), True),
        (CatalogProjectionVersion("2", "5"), False),
        (CatalogProjectionVersion(None, None), True),
    ],
)
async def test_claim_reads_current_code_metadata_without_replacing_successful_data(
    rdb_session: AsyncSession, version: CatalogProjectionVersion, stale: bool
) -> None:
    fixture = await _integration(
        rdb_session, handle="projection-version-claim", provider=LLMProvider.OPENAI
    )
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_integration_catalog(
        rdb_session,
        integration_id=fixture.integration_id,
        provider=LLMProvider.OPENAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
    )
    owner = await rdb_session.get(RDBLLMCatalog, catalog.id)
    assert owner is not None
    owner.last_success_at = _NOW
    owner.diagnostics = {
        "projection_version": {
            "schema_version": version.schema_version,
            "resolver_revision": version.resolver_revision,
        }
    }
    await rdb_session.flush()
    assert repository.projection_version(owner) == version
    decision = await repository.begin_integration_sync(
        rdb_session,
        catalog_id=catalog.id,
        workspace_id=fixture.workspace_id,
        started_at=_NOW,
        trigger=IntegrationCatalogSyncTrigger.STALE_REFRESH,
        required_projection_version=CatalogProjectionVersion("2", "5"),
    )
    if stale:
        assert isinstance(decision, IntegrationCatalogSyncClaim)
        duplicate = await repository.begin_integration_sync(
            rdb_session,
            catalog_id=catalog.id,
            workspace_id=fixture.workspace_id,
            started_at=_NOW + datetime.timedelta(seconds=1),
            trigger=IntegrationCatalogSyncTrigger.STALE_REFRESH,
            required_projection_version=CatalogProjectionVersion("2", "5"),
        )
        assert isinstance(duplicate, IntegrationCatalogSyncPolicyDecision)
        assert (
            duplicate.denial_reason
            is IntegrationCatalogSyncDenialReason.ALREADY_RUNNING
        )
    else:
        assert isinstance(decision, IntegrationCatalogSyncPolicyDecision)
        assert decision.denial_reason is IntegrationCatalogSyncDenialReason.NOT_STALE
    assert owner.last_success_at == _NOW
    assert repository.projection_version(owner) == version
