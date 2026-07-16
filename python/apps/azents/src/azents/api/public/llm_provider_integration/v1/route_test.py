"""Tests for LLM provider integration catalog sync routing."""

from fastapi import BackgroundTasks

from azents.core.enums import LLMCatalogScope, LLMProvider
from azents.core.llm_catalog_sync import IntegrationCatalogSyncTrigger
from azents.services.llm_catalog import IntegrationCatalogProjectionService

from . import enqueue_initial_catalog_sync, enqueue_stale_catalog_sync


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
