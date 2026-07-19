"""xAI OAuth public route contract tests."""

import datetime
from unittest.mock import AsyncMock

from azcommon.result import Success
from fastapi import BackgroundTasks

from azents.core.auth.deps import WorkspaceMember
from azents.core.auth.permissions import Permissions
from azents.core.credentials import XaiOAuthConfig
from azents.core.enums import LLMProvider, WorkspaceUserRole
from azents.core.llm_catalog_sync import IntegrationCatalogSyncTrigger
from azents.core.xai_oauth import XaiOAuthSessionStatus
from azents.repos.llm_provider_integration.data import LLMProviderIntegration
from azents.services.llm_catalog import IntegrationCatalogProjectionService
from azents.services.xai_oauth import XaiOAuthService
from azents.services.xai_oauth.data import XaiOAuthDeviceStatusOutput

from . import poll_device


def _member() -> WorkspaceMember:
    """Build one authenticated workspace member."""
    return WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
        permissions={
            Permissions.LLM_INTEGRATIONS_READ,
            Permissions.LLM_INTEGRATIONS_WRITE,
        },
        session_id="session-1",
    )


def _integration() -> LLMProviderIntegration:
    """Build a public xAI integration without encrypted secrets."""
    now = datetime.datetime.now(datetime.UTC)
    return LLMProviderIntegration(
        id="integration-1",
        workspace_id="workspace-1",
        provider=LLMProvider.XAI_OAUTH,
        name="xAI subscription",
        config=XaiOAuthConfig(
            account_id="account-1",
            email="owner@example.com",
            connection_method="device",
            status="connected",
            entitlement_status=None,
            connected_at=now,
            last_refreshed_at=now,
            last_failed_at=None,
            last_failure_reason=None,
        ),
        enabled=True,
        created_at=now,
        updated_at=now,
    )


async def test_connected_poll_queues_catalog_sync_and_redacts_secrets() -> None:
    """Return the public integration and queue initial catalog sync once."""
    service = AsyncMock(spec=XaiOAuthService)
    service.poll_device.return_value = Success(
        XaiOAuthDeviceStatusOutput(
            session_id="session-1",
            status=XaiOAuthSessionStatus.CONNECTED,
            interval_seconds=5,
            integration=_integration(),
        )
    )
    catalog_service = AsyncMock(spec=IntegrationCatalogProjectionService)
    background_tasks = BackgroundTasks()

    response = await poll_device(
        member=_member(),
        service=service,
        catalog_sync_service=catalog_service,
        background_tasks=background_tasks,
        session_id="session-1",
    )
    payload = response.model_dump(mode="json")

    assert payload["integration"]["provider"] == "xai_oauth"
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].kwargs["integration_id"] == "integration-1"
    await background_tasks()
    catalog_service.sync_integration_catalog.assert_awaited_once_with(
        integration_id="integration-1",
        workspace_id="workspace-1",
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )
    serialized = str(payload).lower()
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "device_code" not in serialized


async def test_pending_poll_does_not_queue_catalog_sync() -> None:
    """Do not sync a catalog until the provider connection completes."""
    service = AsyncMock(spec=XaiOAuthService)
    service.poll_device.return_value = Success(
        XaiOAuthDeviceStatusOutput(
            session_id="session-1",
            status=XaiOAuthSessionStatus.PENDING,
            interval_seconds=5,
            integration=None,
        )
    )
    background_tasks = BackgroundTasks()

    response = await poll_device(
        member=_member(),
        service=service,
        catalog_sync_service=object.__new__(IntegrationCatalogProjectionService),
        background_tasks=background_tasks,
        session_id="session-1",
    )

    assert response.integration is None
    assert background_tasks.tasks == []
