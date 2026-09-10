"""Tests for LLM provider integration catalog sync routing."""

import datetime
from unittest.mock import AsyncMock

import pytest
import pytz
from azcommon.result import Failure, Success
from fastapi import BackgroundTasks, HTTPException

from azents.core.auth.deps import WorkspaceMember
from azents.core.auth.permissions import Permissions
from azents.core.enums import LLMCatalogScope, LLMProvider, WorkspaceUserRole
from azents.core.llm_catalog_sync import IntegrationCatalogSyncTrigger
from azents.services.image_generation_catalog import (
    ImageGenerationCatalogService,
    default_only_image_generation_catalog,
)
from azents.services.llm_catalog import (
    IntegrationCatalogProjectionService,
    IntegrationCatalogSyncThrottled,
)

from . import (
    enqueue_initial_catalog_sync,
    enqueue_initial_image_catalog_sync,
    enqueue_stale_catalog_sync,
    enqueue_stale_image_catalog_sync,
    get_image_model_catalog,
    sync_image_model_catalog,
    sync_integration_catalog,
)


def _service() -> IntegrationCatalogProjectionService:
    return object.__new__(IntegrationCatalogProjectionService)


def _image_service() -> ImageGenerationCatalogService:
    return object.__new__(ImageGenerationCatalogService)


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


@pytest.mark.parametrize(
    "provider",
    [LLMProvider.AWS_BEDROCK, LLMProvider.XAI, LLMProvider.XAI_OAUTH],
)
def test_create_queues_supported_integration_catalog_sync(
    provider: LLMProvider,
) -> None:
    background_tasks = BackgroundTasks()

    enqueue_initial_catalog_sync(
        background_tasks,
        service=_service(),
        integration_id="integration",
        workspace_id="workspace",
        provider=provider,
        name=provider.value,
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


def test_image_catalog_refresh_queue_respects_stale_and_retry_state() -> None:
    """Only stale supported image catalogs with retry access queue refresh."""
    queued = BackgroundTasks()
    blocked = BackgroundTasks()
    unsupported = BackgroundTasks()

    enqueue_stale_image_catalog_sync(
        queued,
        service=_image_service(),
        integration_id="integration",
        workspace_id="workspace",
        stale=True,
        explicit_selection_supported=True,
        automatic_retry_blocked=False,
    )
    enqueue_stale_image_catalog_sync(
        blocked,
        service=_image_service(),
        integration_id="blocked",
        workspace_id="workspace",
        stale=True,
        explicit_selection_supported=True,
        automatic_retry_blocked=True,
    )
    enqueue_stale_image_catalog_sync(
        unsupported,
        service=_image_service(),
        integration_id="unsupported",
        workspace_id="workspace",
        stale=True,
        explicit_selection_supported=False,
        automatic_retry_blocked=False,
    )

    assert len(queued.tasks) == 1
    assert (
        queued.tasks[0].kwargs["trigger"] == IntegrationCatalogSyncTrigger.STALE_REFRESH
    )
    assert blocked.tasks == []
    assert unsupported.tasks == []


def test_initial_image_sync_only_queues_enabled_openai_api_key() -> None:
    """Default-only and disabled integrations never run image discovery."""
    openai_tasks = BackgroundTasks()
    disabled_tasks = BackgroundTasks()
    oauth_tasks = BackgroundTasks()

    enqueue_initial_image_catalog_sync(
        openai_tasks,
        service=_image_service(),
        integration_id="openai",
        workspace_id="workspace",
        provider=LLMProvider.OPENAI,
        enabled=True,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )
    enqueue_initial_image_catalog_sync(
        disabled_tasks,
        service=_image_service(),
        integration_id="disabled",
        workspace_id="workspace",
        provider=LLMProvider.OPENAI,
        enabled=False,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )
    enqueue_initial_image_catalog_sync(
        oauth_tasks,
        service=_image_service(),
        integration_id="oauth",
        workspace_id="workspace",
        provider=LLMProvider.CHATGPT_OAUTH,
        enabled=True,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )

    assert len(openai_tasks.tasks) == 1
    assert disabled_tasks.tasks == []
    assert oauth_tasks.tasks == []


async def test_image_catalog_get_returns_stored_default_only_state() -> None:
    """Read permission returns the service projection without discovery."""
    member = WorkspaceMember(
        user_id="user",
        workspace_id="workspace",
        workspace_user_id="workspace-user",
        role=WorkspaceUserRole.MEMBER,
        permissions={Permissions.LLM_INTEGRATIONS_READ},
        session_id="session",
    )
    service = AsyncMock(spec=ImageGenerationCatalogService)
    service.read.return_value = Success(
        default_only_image_generation_catalog(
            provider=LLMProvider.CHATGPT_OAUTH,
            integration_enabled=True,
            current_configuration_version=4,
        )
    )
    background_tasks = BackgroundTasks()

    response = await get_image_model_catalog(
        member=member,
        service=service,
        background_tasks=background_tasks,
        integration_id="integration",
    )

    assert response.default_available is True
    assert response.explicit_selection_supported is False
    assert response.current_configuration_version == 4
    assert response.entries == []
    assert background_tasks.tasks == []


async def test_image_catalog_explicit_sync_formats_retry_time() -> None:
    """Image sync uses the shared HTTP-date throttle contract."""
    retry_at = datetime.datetime(2026, 9, 10, 12, 0, 30, tzinfo=pytz.UTC)
    member = WorkspaceMember(
        user_id="user",
        workspace_id="workspace",
        workspace_user_id="workspace-user",
        role=WorkspaceUserRole.OWNER,
        permissions={Permissions.LLM_INTEGRATIONS_WRITE},
        session_id="session",
    )
    service = AsyncMock(spec=ImageGenerationCatalogService)
    service.sync.return_value = Failure(
        IntegrationCatalogSyncThrottled(retry_at=retry_at)
    )

    with pytest.raises(HTTPException) as exc_info:
        await sync_image_model_catalog(
            member=member,
            service=service,
            integration_id="integration",
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "Thu, 10 Sep 2026 12:00:30 GMT"}


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
