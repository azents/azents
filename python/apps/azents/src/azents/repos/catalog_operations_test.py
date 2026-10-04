"""Current publication atomicity, exact-input races and completed boundaries."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMCatalogPurpose, LLMCatalogScope, LLMProvider
from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    CATALOG_SOURCE_SCHEMA_VERSION,
)
from azents.core.model_metadata_collection_data import FetchedModelMetadataSource
from azents.rdb.models.llm_catalog import RDBLLMCatalog
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.model_metadata_source import RDBModelMetadataSource
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_model_capabilities_data import (
    ActiveReadScope,
    CapturedActiveChoiceInputs,
)
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    IntegrationCatalogSyncClaim,
    LLMCatalogEntryList,
)
from azents.repos.llm_catalog_operations import (
    CatalogPublicationSourceChanged,
    CatalogPublicationSuperseded,
    LLMCatalogOperationsRepository,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.model_catalog_sync_state import (
    current_sync_status,
    fail_sync,
    start_sync,
    succeed_sync,
)
from azents.repos.model_metadata_operations import (
    ModelMetadataSourceOperations,
    SourceSyncAlreadyRunning,
    SystemCatalogReplacement,
    _material_reduction,
)
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSource
from azents.testing.model_metadata import make_test_source, make_test_source_payload

_NOW = datetime.datetime(2026, 10, 3, tzinfo=datetime.UTC)


class _Transactions:
    """Explicit transaction outcomes; no sleeping or external I/O."""

    def __init__(self) -> None:
        self.session = AsyncMock(spec=AsyncSession)
        self.events: list[str] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        self.events.append("begin")
        try:
            yield self.session
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")


async def test_picker_bundles_local_capture_before_finishing_the_same_transaction() -> (
    None
):
    transactions = _Transactions()
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    active = AsyncMock(spec=ActiveModelCapabilitiesRepository)
    scope = ActiveReadScope(
        workspace_id="workspace", integrations=(), source_metadata=None
    )
    inputs = CapturedActiveChoiceInputs(
        workspace_id="workspace",
        choices=(),
        catalog_choices=(),
        source_metadata=None,
        source_expectations=(),
    )
    page = LLMCatalogEntryList(
        catalog=LLMCatalogRepository.build_catalog(_catalog()), entries=[], total=0
    )

    async def prepare(
        session: AsyncSession, *, workspace_id: str, integration_ids: tuple[str, ...]
    ) -> ActiveReadScope:
        assert session is transactions.session
        assert workspace_id == "workspace"
        assert integration_ids == ("integration",)
        assert transactions.events == ["begin"]
        transactions.events.append("prepare_integration_source_scope")
        return scope

    async def read(
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str,
        purpose: LLMCatalogPurpose,
        search: str | None,
        limit: int,
        offset: int,
    ) -> LLMCatalogEntryList:
        assert session is transactions.session
        assert transactions.events[-1] == "prepare_integration_source_scope"
        transactions.events.append("read_catalog_page")
        return page

    async def capture(
        session: AsyncSession,
        *,
        scope: ActiveReadScope,
        integration_id: str,
        entries: tuple[object, ...],
    ) -> CapturedActiveChoiceInputs:
        assert session is transactions.session
        assert scope.workspace_id == "workspace"
        assert integration_id == "integration"
        assert entries == ()
        assert transactions.events[-1] == "read_catalog_page"
        transactions.events.append("capture_page_exact_sources")
        return inputs

    active.prepare_read_scope_in_session.side_effect = prepare
    active.capture_current_entries_in_session.side_effect = capture
    catalogs.list_entries_by_integration.side_effect = read
    catalogs.get_latest_integration_sync_for_workspace.return_value = None
    catalogs.projection_version.return_value = None
    operations = LLMCatalogOperationsRepository(
        session_manager=transactions,
        catalog_repository=catalogs,
        integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
        source_repository=AsyncMock(spec=ModelMetadataSourceRepository),
        active_repository=active,
    )
    result = await operations.read_page(
        integration_id="integration",
        workspace_id="workspace",
        search=None,
        limit=10,
        offset=0,
    )
    assert result is not None
    assert result.page is page
    assert result.active_inputs is inputs
    assert transactions.events == [
        "begin",
        "prepare_integration_source_scope",
        "read_catalog_page",
        "capture_page_exact_sources",
        "commit",
    ]
    active.capture_current_entries_in_session.assert_awaited_once()
    active.capture_exact_choices.assert_not_awaited()


def _catalog(
    *, purpose: LLMCatalogPurpose = LLMCatalogPurpose.CONVERSATION
) -> RDBLLMCatalog:
    owner = RDBLLMCatalog(
        id="catalog",
        scope=LLMCatalogScope.INTEGRATION,
        provider=LLMProvider.XAI,
        purpose=purpose,
        provider_integration_id="integration",
        image_usable=None if purpose == LLMCatalogPurpose.CONVERSATION else False,
    )
    owner.entry_count = 0
    owner.visible_count = 0
    owner.hidden_count = 0
    owner.last_success_at = _NOW
    start_sync(owner, work_token="work", started_at=_NOW, diagnostics=None)
    return owner


def _source_owner() -> RDBModelMetadataSource:
    owner = RDBModelMetadataSource(
        source_key=CATALOG_SOURCE_KEY,
        source_kind=CATALOG_SOURCE_KIND,
        source_schema_version=CATALOG_SOURCE_SCHEMA_VERSION,
    )
    start_sync(owner, work_token="work", started_at=_NOW, diagnostics=None)
    return owner


def _integration() -> RDBLLMProviderIntegration:
    owner = RDBLLMProviderIntegration(
        workspace_id="workspace",
        provider=LLMProvider.XAI,
        name="Integration",
        encrypted_credentials="opaque-test",
        config=None,
        enabled=True,
    )
    owner.id = "integration"
    return owner


def _fetched(source: ModelMetadataSource) -> FetchedModelMetadataSource:
    return FetchedModelMetadataSource(
        source_kind=source.source_kind,
        source_schema_version=source.source_schema_version,
        source_url=source.source_url,
        producer_name=source.producer_name,
        producer_version=source.producer_version,
        provider_count=source.provider_count,
        model_count=source.model_count,
        payload=source.payload,
        models=source.models,
        collected_at=source.collected_at,
    )


@pytest.mark.asyncio
async def test_prepared_source_change_rejects_before_any_catalog_write() -> None:
    transactions = _Transactions()
    catalog = _catalog()
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    catalogs.lock_integration.return_value = _integration()
    catalogs.lock_catalog.return_value = catalog
    sources = AsyncMock(spec=ModelMetadataSourceRepository)
    sources.projection_inputs_match.return_value = False
    operations = LLMCatalogOperationsRepository(
        session_manager=transactions,
        catalog_repository=catalogs,
        integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
        source_repository=sources,
        active_repository=AsyncMock(spec=ActiveModelCapabilitiesRepository),
    )
    result = await operations.publish(
        catalog=LLMCatalogRepository.build_catalog(catalog),
        claim=IntegrationCatalogSyncClaim(
            work_token="work", catalog_configuration_version=1
        ),
        entries=[],
        expected_source_metadata=None,
        expected_source_models=(),
        diagnostics=None,
        sync_diagnostics=None,
        fetched_count=0,
        skipped_count=0,
        finished_at=_NOW,
    )
    assert isinstance(result, CatalogPublicationSourceChanged)
    catalogs.replace_current_entries.assert_not_awaited()
    catalogs.complete_sync.assert_not_awaited()
    assert transactions.events == ["begin", "commit"]


@pytest.mark.asyncio
async def test_credential_change_rejects_old_discovery_even_with_current_work() -> None:
    transactions = _Transactions()
    catalog = _catalog()
    integration = _integration()
    integration.catalog_configuration_version = 2
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    catalogs.lock_integration.return_value = integration
    catalogs.lock_catalog.return_value = catalog
    sources = AsyncMock(spec=ModelMetadataSourceRepository)
    sources.projection_inputs_match.return_value = True
    operations = LLMCatalogOperationsRepository(
        session_manager=transactions,
        catalog_repository=catalogs,
        integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
        source_repository=sources,
        active_repository=AsyncMock(spec=ActiveModelCapabilitiesRepository),
    )
    result = await operations.publish(
        catalog=LLMCatalogRepository.build_catalog(catalog),
        claim=IntegrationCatalogSyncClaim(
            work_token="work", catalog_configuration_version=1
        ),
        entries=[],
        expected_source_metadata=None,
        expected_source_models=(),
        diagnostics=None,
        sync_diagnostics=None,
        fetched_count=0,
        skipped_count=0,
        finished_at=_NOW,
    )
    assert isinstance(result, CatalogPublicationSuperseded)
    catalogs.replace_current_entries.assert_not_awaited()
    assert catalog.sync_work_token is None
    assert catalog.sync_status is not None
    assert catalog.sync_status.value == "failed"
    assert catalog.last_success_at == _NOW
    assert transactions.events == ["begin", "commit"]


@pytest.mark.asyncio
async def test_failed_current_write_exits_through_rollback() -> None:
    transactions = _Transactions()
    catalog = _catalog()
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    catalogs.lock_integration.return_value = _integration()
    catalogs.lock_catalog.return_value = catalog
    catalogs.replace_current_entries.side_effect = ValueError(
        "Invalid current entries."
    )
    sources = AsyncMock(spec=ModelMetadataSourceRepository)
    sources.projection_inputs_match.return_value = True
    operations = LLMCatalogOperationsRepository(
        session_manager=transactions,
        catalog_repository=catalogs,
        integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
        source_repository=sources,
        active_repository=AsyncMock(spec=ActiveModelCapabilitiesRepository),
    )
    with pytest.raises(ValueError, match="Invalid current entries"):
        await operations.publish(
            catalog=LLMCatalogRepository.build_catalog(catalog),
            claim=IntegrationCatalogSyncClaim(
                work_token="work", catalog_configuration_version=1
            ),
            entries=[],
            expected_source_metadata=None,
            expected_source_models=(),
            diagnostics=None,
            sync_diagnostics=None,
            fetched_count=0,
            skipped_count=0,
            finished_at=_NOW,
        )
    catalogs.complete_sync.assert_not_awaited()
    assert transactions.events == ["begin", "rollback"]


@pytest.mark.asyncio
async def test_source_work_token_is_not_source_freshness_authority() -> None:
    transactions = _Transactions()
    sources = AsyncMock(spec=ModelMetadataSourceRepository)
    owner = _source_owner()
    sources.lock_authority.return_value = owner
    previous = make_test_source(
        make_test_source_payload(
            {"literal": {"litellm_provider": "openai", "max_input_tokens": 4096}}
        )
    )
    changed = make_test_source(
        make_test_source_payload(
            {"literal": {"litellm_provider": "openai", "max_input_tokens": 8192}}
        )
    )
    sources.get_current.return_value = changed
    operations = ModelMetadataSourceOperations(
        session_manager=transactions,
        repository=sources,
        catalog_repository=AsyncMock(spec=LLMCatalogRepository),
    )
    replacements = [
        SystemCatalogReplacement(provider=provider, entries=[], diagnostics=None)
        for provider in (
            LLMProvider.OPENAI,
            LLMProvider.ANTHROPIC,
            LLMProvider.GOOGLE_GEMINI,
        )
    ]
    result = await operations.publish(
        work_token="work",
        fetched=_fetched(previous),
        expected_source=previous,
        replacements=replacements,
        finished_at=_NOW,
    )
    assert result.source_changed
    assert owner.sync_work_token == "work"
    sources.replace_current.assert_not_awaited()
    assert transactions.events == ["begin", "commit"]


@pytest.mark.asyncio
async def test_atomic_system_lease_check_does_not_reclaim_unexpired_work() -> None:
    transactions = _Transactions()
    source_owner = _source_owner()
    catalog = _catalog()
    catalog.scope = LLMCatalogScope.SYSTEM
    catalog.provider_integration_id = None
    sources = AsyncMock(spec=ModelMetadataSourceRepository)
    sources.lock_authority.return_value = source_owner
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    catalogs.lock_catalog.return_value = catalog
    records = [
        Mock(id=f"owner-{provider.value}", provider=provider)
        for provider in (
            LLMProvider.OPENAI,
            LLMProvider.ANTHROPIC,
            LLMProvider.GOOGLE_GEMINI,
        )
    ]
    transactions.session.execute.return_value = records
    operations = ModelMetadataSourceOperations(
        session_manager=transactions, repository=sources, catalog_repository=catalogs
    )
    outcome = await operations.begin_sync(
        started_at=_NOW + datetime.timedelta(minutes=1)
    )
    assert isinstance(outcome, SourceSyncAlreadyRunning)
    assert outcome.work_token == "work"
    sources.begin_sync.assert_not_awaited()
    assert transactions.events == ["begin", "commit"]


def test_completed_work_clears_token_but_preserves_success_for_failure() -> None:
    owner = _catalog()
    succeed_sync(
        owner,
        work_token="work",
        finished_at=_NOW,
        fetched_count=1,
        matched_count=1,
        skipped_count=0,
        hidden_count=0,
        diagnostics=None,
    )
    start_sync(
        owner,
        work_token="next",
        started_at=_NOW + datetime.timedelta(seconds=1),
        diagnostics=None,
    )
    assert fail_sync(
        owner,
        work_token="next",
        finished_at=_NOW + datetime.timedelta(seconds=2),
        failure_code="Failed",
        failure_message="Refresh failed.",
        action_hint=None,
        diagnostics={"automatic_retry_blocked": True},
    )
    status = current_sync_status(owner)
    assert status is not None
    assert status.work_token is None
    assert status.status.value == "failed"
    assert owner.last_success_at == _NOW
    assert owner.image_usable is None


def test_superseded_failure_cannot_mutate_one_current_state() -> None:
    owner = _source_owner()
    start_sync(owner, work_token="new", started_at=_NOW, diagnostics=None)
    assert not fail_sync(
        owner,
        work_token="work",
        finished_at=_NOW,
        failure_code="Late",
        failure_message="Late failure.",
        action_hint=None,
        diagnostics=None,
    )
    assert owner.sync_work_token == "new"
    assert owner.sync_status is not None
    assert owner.sync_status.value == "running"


@pytest.mark.asyncio
async def test_only_expired_system_lease_is_reclaimed_by_combined_work() -> None:
    transactions = _Transactions()
    sources = AsyncMock(spec=ModelMetadataSourceRepository)
    sources.lock_authority.return_value = _source_owner()
    sources.begin_sync.return_value = "new-work"
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    owners: dict[str, RDBLLMCatalog] = {}
    for provider in (
        LLMProvider.OPENAI,
        LLMProvider.ANTHROPIC,
        LLMProvider.GOOGLE_GEMINI,
    ):
        owner = _catalog()
        owner.id = provider.value
        owner.provider = provider
        owner.scope = LLMCatalogScope.SYSTEM
        owner.provider_integration_id = None
        owners[owner.id] = owner
    records = [Mock(id=owner.id, provider=owner.provider) for owner in owners.values()]
    transactions.session.execute.return_value = records

    async def lock_owner(
        session: AsyncSession, *, catalog_id: str, shared: bool = False
    ) -> RDBLLMCatalog:
        return owners[catalog_id]

    catalogs.lock_catalog.side_effect = lock_owner
    operations = ModelMetadataSourceOperations(
        session_manager=transactions,
        repository=sources,
        catalog_repository=catalogs,
    )
    outcome = await operations.begin_sync(
        started_at=_NOW + datetime.timedelta(minutes=6)
    )
    assert outcome == "new-work"
    sources.begin_sync.assert_awaited_once()
    assert [
        call.kwargs["catalog_id"] for call in catalogs.lock_catalog.await_args_list
    ] == sorted(owners)
    assert all(owner.sync_work_token == "new-work" for owner in owners.values())
    assert all(owner.last_success_at == _NOW for owner in owners.values())
    assert transactions.events == ["begin", "commit"]


@pytest.mark.parametrize(
    ("provider", "removed_count", "expected"),
    [
        ("openai", 50, "global"),
        ("anthropic", 5, "provider:anthropic"),
        ("anthropic", 4, None),
    ],
)
def test_existing_source_shrink_thresholds(
    provider: str, removed_count: int, expected: str | None
) -> None:
    original: dict[str, object] = {
        f"model-{index}": {"litellm_provider": provider}
        for index in range(250 if provider == "openai" else 25)
    }
    before = make_test_source(make_test_source_payload(original))
    retained = dict(list(original.items())[removed_count:])
    fetched = _fetched(make_test_source(make_test_source_payload(retained)))
    assert _material_reduction(previous=before, fetched=fetched) == expected
