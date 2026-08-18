"""xAI OAuth public route contract tests."""

import datetime
from unittest.mock import AsyncMock

from azcommon.result import Success
from fastapi import BackgroundTasks

from azents.core.auth.deps import WorkspaceMember
from azents.core.auth.permissions import Permissions
from azents.core.credentials import XaiOAuthConfig
from azents.core.enums import LLMProvider, WorkspaceUserRole
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
    """Build one public xAI OAuth integration."""
    now = datetime.datetime.now(datetime.UTC)
    return LLMProviderIntegration(
        id="integration-1",
        workspace_id="workspace-1",
        provider=LLMProvider.XAI_OAUTH,
        name="xAI Grok OAuth",
        config=XaiOAuthConfig(
            account_id="account-1",
            email=None,
            connection_method="device",
            status="connected",
            connected_at=now,
            last_refreshed_at=now,
        ),
        enabled=True,
        created_at=now,
        updated_at=now,
    )


async def test_connected_poll_queues_initial_catalog_sync() -> None:
    """Return the integration and queue its credential-scoped model discovery."""
    service = AsyncMock(spec=XaiOAuthService)
    service.poll_device.return_value = Success(
        XaiOAuthDeviceStatusOutput(
            session_id="session-1",
            status=XaiOAuthSessionStatus.CONNECTED,
            interval_seconds=5,
            integration=_integration(),
        )
    )
    catalog_service = object.__new__(IntegrationCatalogProjectionService)
    background_tasks = BackgroundTasks()

    response = await poll_device(
        member=_member(),
        service=service,
        catalog_sync_service=catalog_service,
        background_tasks=background_tasks,
        session_id="session-1",
    )

    assert response.integration is not None
    assert response.integration.provider == LLMProvider.XAI_OAUTH
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.kwargs["integration_id"] == "integration-1"
    assert task.kwargs["workspace_id"] == "workspace-1"
