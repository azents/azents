"""LLM catalog read service tests."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMProvider,
)
from azents.core.llm_catalog_sync import CatalogProjectionVersion
from azents.core.model_catalog_source import CATALOG_SOURCE_KEY
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    LLMCatalog,
    LLMCatalogEntryList,
    LLMCatalogSyncAttempt,
)
from azents.repos.llm_catalog_operations import LLMCatalogOperationsRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.services.llm_catalog import ModelCatalogReadService


class _SessionManager:
    """Async session manager used by tests."""

    async def __aenter__(self) -> AsyncSession:
        return AsyncSession()

    async def __aexit__(self, *args: object) -> bool | None:
        return None

    def __call__(self) -> "_SessionManager":
        return self


class _CatalogRepository(LLMCatalogRepository):
    """Catalog repository used by tests."""

    def __init__(
        self,
        page: LLMCatalogEntryList,
        version: CatalogProjectionVersion | None,
    ) -> None:
        self.page = page
        self.version = version

    async def get_current_snapshot_projection_version(
        self,
        session: AsyncSession,
        *,
        catalog: LLMCatalog,
    ) -> CatalogProjectionVersion | None:
        del session, catalog
        return self.version

    async def list_entries_by_integration(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str,
        purpose: LLMCatalogPurpose,
        search: str | None,
        limit: int,
        offset: int,
    ) -> LLMCatalogEntryList | None:
        del session, integration_id, workspace_id, purpose, search, limit, offset
        return self.page

    async def get_latest_integration_attempt_for_workspace(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
    ) -> LLMCatalogSyncAttempt | None:
        del session, workspace_id
        return None


@pytest.mark.asyncio
async def test_read_service_returns_latest_failed_attempt_without_snapshot() -> None:
    """Return the latest failed attempt even when no snapshot exists."""
    now = datetime.datetime.now(datetime.UTC)
    page = LLMCatalogEntryList(
        catalog=LLMCatalog(
            id="catalog-id",
            scope=LLMCatalogScope.INTEGRATION,
            provider=LLMProvider.AWS_BEDROCK,
            purpose=LLMCatalogPurpose.CONVERSATION,
            provider_integration_id="integration-id",
            current_snapshot_id=None,
            latest_attempt_id="attempt-id",
        ),
        entries=[],
        total=0,
        current_snapshot_created_at=None,
        latest_attempt=LLMCatalogSyncAttempt(
            id="attempt-id",
            catalog_id="catalog-id",
            source_key=CATALOG_SOURCE_KEY,
            status=LLMCatalogAttemptStatus.FAILED,
            started_at=now,
            finished_at=now,
            produced_snapshot_id=None,
            failure_code="AccessDeniedException",
            failure_message="Provider listing failed.",
            action_hint="Check integration credentials and provider permissions.",
            fetched_count=0,
            matched_count=0,
            skipped_count=0,
            hidden_count=0,
            diagnostics={"failure_category": "user_catalog_credentials_or_permissions"},
            catalog_configuration_version=1,
        ),
    )
    service = ModelCatalogReadService(
        operations=LLMCatalogOperationsRepository(
            session_manager=_SessionManager(),
            catalog_repository=_CatalogRepository(page, None),
            integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
        ),
    )

    result = await service.list_entries_by_integration(
        integration_id="integration-id",
        workspace_id="workspace-id",
        search=None,
        limit=50,
        offset=0,
    )

    assert isinstance(result, Success)
    assert result.value.current_snapshot_id is None
    assert result.value.entries == []
    assert result.value.latest_attempt is not None
    assert result.value.latest_attempt.status == "failed"
    assert result.value.latest_attempt.failure_code == "AccessDeniedException"


@pytest.mark.parametrize(
    ("version", "stale"),
    [
        (CatalogProjectionVersion("1", "5"), True),
        (CatalogProjectionVersion("2", "4"), True),
        (CatalogProjectionVersion(None, None), True),
        (CatalogProjectionVersion("2", "5"), False),
    ],
)
async def test_read_policy_reports_fresh_stored_version_drift_without_mutation(
    version: CatalogProjectionVersion,
    stale: bool,
) -> None:
    """Lazy refresh learns stored version drift while returning the last good page."""
    now = datetime.datetime.now(datetime.UTC)
    page = LLMCatalogEntryList(
        catalog=LLMCatalog(
            id="catalog-id",
            scope=LLMCatalogScope.INTEGRATION,
            provider=LLMProvider.OPENROUTER,
            purpose=LLMCatalogPurpose.CONVERSATION,
            provider_integration_id="integration-id",
            current_snapshot_id="stored-snapshot",
            latest_attempt_id=None,
        ),
        entries=[],
        total=0,
        current_snapshot_created_at=now,
        latest_attempt=None,
    )
    repository = _CatalogRepository(page, version)
    service = ModelCatalogReadService(
        operations=LLMCatalogOperationsRepository(
            session_manager=_SessionManager(),
            catalog_repository=repository,
            integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
        ),
    )
    result = await service.list_entries_by_integration(
        integration_id="integration-id",
        workspace_id="workspace-id",
        search=None,
        limit=50,
        offset=0,
    )
    assert isinstance(result, Success)
    assert result.value.stale is stale
    assert result.value.current_snapshot_id == "stored-snapshot"
    assert result.value.current_snapshot_created_at == now
    assert repository.page is page
    assert repository.version == version
