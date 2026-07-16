"""Tests for LLM provider integration catalog sync routing."""

import datetime
from unittest.mock import AsyncMock

import pytz
from azcommon.result import Failure
from fastapi import BackgroundTasks, HTTPException

from azents.core.auth.deps import WorkspaceMember
from azents.core.auth.permissions import Permissions
from azents.core.enums import LLMCatalogScope, LLMProvider, WorkspaceUserRole
from azents.core.llm_catalog_sync import IntegrationCatalogSyncTrigger
from azents.services.llm_catalog import (
    IntegrationCatalogProjectionService,
    IntegrationCatalogSyncThrottled,
)

from . import (
    enqueue_initial_catalog_sync,
    enqueue_stale_catalog_sync,
    sync_integration_catalog,
)


def _service() -> IntegrationCatalogProjectionService:
    return object.__new__(IntegrationCatalogProjectionService)


def test_stale_integration_catalog_read_queues_lazy_refresh() -> None:
    background_tasks = BackgroundTasks()

    enqueue_stale_catalog_sync(
        background_tasks,
        service=_service(),
        integration_id="integration",
        workspace_id="workspace",
        catalog_scope=LLMCatalogScope.INTEGRATION,
        stale=True,
    )

    assert len(background_tasks.tasks) == 1
    assert (
        background_tasks.tasks[0].kwargs["trigger"]
        == IntegrationCatalogSyncTrigger.STALE_REFRESH
    )


def test_fresh_or_system_catalog_read_does_not_queue_lazy_refresh() -> None:
    fresh_tasks = BackgroundTasks()
    system_tasks = BackgroundTasks()

    enqueue_stale_catalog_sync(
        fresh_tasks,
        service=_service(),
        integration_id="fresh",
        workspace_id="workspace",
        catalog_scope=LLMCatalogScope.INTEGRATION,
        stale=False,
    )
    enqueue_stale_catalog_sync(
        system_tasks,
        service=_service(),
        integration_id="system",
        workspace_id="workspace",
        catalog_scope=LLMCatalogScope.SYSTEM,
        stale=True,
    )

    assert fresh_tasks.tasks == []
    assert system_tasks.tasks == []


def test_create_queues_supported_integration_catalog_sync() -> None:
    background_tasks = BackgroundTasks()

    enqueue_initial_catalog_sync(
        background_tasks,
        service=_service(),
        integration_id="integration",
        workspace_id="workspace",
        provider=LLMProvider.AWS_BEDROCK,
        name="Bedrock",
        enabled=True,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )

    assert len(background_tasks.tasks) == 1
    assert (
        background_tasks.tasks[0].kwargs["trigger"]
        == IntegrationCatalogSyncTrigger.CREATE
    )


def test_deterministic_fixture_queues_initial_sync_for_e2e() -> None:
    background_tasks = BackgroundTasks()

    enqueue_initial_catalog_sync(
        background_tasks,
        service=_service(),
        integration_id="integration",
        workspace_id="workspace",
        provider=LLMProvider.OPENAI,
        name="__testenv_model_listing:deterministic-success",
        enabled=True,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )

    assert len(background_tasks.tasks) == 1


def test_disabled_or_system_catalog_integration_does_not_queue_sync() -> None:
    disabled_tasks = BackgroundTasks()
    system_tasks = BackgroundTasks()

    enqueue_initial_catalog_sync(
        disabled_tasks,
        service=_service(),
        integration_id="disabled",
        workspace_id="workspace",
        provider=LLMProvider.GOOGLE_VERTEX_AI,
        name="Vertex",
        enabled=False,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )
    enqueue_initial_catalog_sync(
        system_tasks,
        service=_service(),
        integration_id="system",
        workspace_id="workspace",
        provider=LLMProvider.OPENAI,
        name="OpenAI",
        enabled=True,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )

    assert disabled_tasks.tasks == []
    assert system_tasks.tasks == []


async def test_explicit_sync_formats_pytz_retry_time_as_http_date() -> None:
    retry_at = datetime.datetime(2026, 7, 16, 12, 0, 30, tzinfo=pytz.UTC)
    member = WorkspaceMember(
        user_id="user",
        workspace_id="workspace",
        workspace_user_id="workspace-user",
        role=WorkspaceUserRole.OWNER,
        permissions={Permissions.LLM_INTEGRATIONS_WRITE},
        session_id="session",
    )
    service = AsyncMock(spec=IntegrationCatalogProjectionService)
    service.sync_integration_catalog.return_value = Failure(
        IntegrationCatalogSyncThrottled(retry_at=retry_at)
    )

    try:
        await sync_integration_catalog(
            member=member,
            service=service,
            integration_id="integration",
        )
    except HTTPException as exc:
        assert exc.status_code == 429
        assert exc.headers == {"Retry-After": "Thu, 16 Jul 2026 12:00:30 GMT"}
    else:
        raise AssertionError("Expected HTTPException")
