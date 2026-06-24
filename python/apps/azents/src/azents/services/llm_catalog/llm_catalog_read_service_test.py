"""LLM catalog read service tests."""

from __future__ import annotations

import datetime

import pytest
from azcommon.result import Success

from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogLowererTarget,
    LLMCatalogScope,
    LLMProvider,
)
from azents.repos.llm_catalog.data import (
    LLMCatalog,
    LLMCatalogEntryList,
    LLMCatalogSyncAttempt,
)
from azents.services.llm_catalog import ModelCatalogReadService


class _SessionManager:
    """테스트용 async session manager."""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
        return None

    def __call__(self) -> "_SessionManager":
        return self


class _CatalogRepository:
    """테스트용 catalog repository."""

    def __init__(self, page: LLMCatalogEntryList) -> None:
        self.page = page

    async def list_entries_by_integration(
        self,
        _session: object,
        *,
        integration_id: str,
        workspace_id: str,
        search: str | None,
        limit: int,
        offset: int,
    ) -> LLMCatalogEntryList:
        return self.page


@pytest.mark.asyncio
async def test_read_service_returns_latest_failed_attempt_without_snapshot() -> None:
    """현재 snapshot이 없어도 latest 실패 attempt를 domain state로 반환한다."""
    now = datetime.datetime.now(datetime.UTC)
    page = LLMCatalogEntryList(
        catalog=LLMCatalog(
            id="catalog-id",
            scope=LLMCatalogScope.INTEGRATION,
            provider=LLMProvider.AWS_BEDROCK,
            provider_integration_id="integration-id",
            lowerer_target=LLMCatalogLowererTarget.LITELLM,
            current_snapshot_id=None,
            latest_attempt_id="attempt-id",
        ),
        entries=[],
        total=0,
        current_snapshot_created_at=None,
        latest_attempt=LLMCatalogSyncAttempt(
            id="attempt-id",
            catalog_id="catalog-id",
            source_key="litellm_model_cost",
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
        ),
    )
    service = ModelCatalogReadService(
        session_manager=_SessionManager(),  # type: ignore[arg-type]
        catalog_repository=_CatalogRepository(page),  # type: ignore[arg-type]
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
