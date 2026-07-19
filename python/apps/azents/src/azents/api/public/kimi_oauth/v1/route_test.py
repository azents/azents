"""Kimi OAuth public route contract tests."""

import datetime
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from fastapi import BackgroundTasks, HTTPException
from fastapi.routing import APIRoute

from azents.core.auth.deps import WorkspaceMember
from azents.core.auth.permissions import Permissions
from azents.core.credentials import KimiOAuthConfig
from azents.core.enums import LLMProvider, WorkspaceUserRole
from azents.core.kimi_oauth import KimiOAuthSessionStatus
from azents.repos.llm_provider_integration.data import LLMProviderIntegration
from azents.services.kimi_oauth.data import (
    InvalidSession,
    KimiOAuthDeviceStartOutput,
    KimiOAuthDeviceStatusOutput,
    ProviderRejected,
    ProviderUnavailable,
    SessionNotFound,
    SessionTransitionFailed,
)
from azents.services.kimi_oauth.service import KimiOAuthService
from azents.services.llm_catalog import IntegrationCatalogProjectionService

from .route import poll_device, router, start_device


def _member(*, write: bool = True) -> WorkspaceMember:
    """Build one authenticated workspace member."""
    permissions = {Permissions.LLM_INTEGRATIONS_READ}
    if write:
        permissions.add(Permissions.LLM_INTEGRATIONS_WRITE)
    return WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
        permissions=permissions,
        session_id="session-1",
    )


def _integration() -> LLMProviderIntegration:
    """Build a public Kimi integration without encrypted secrets."""
    now = datetime.datetime.now(datetime.UTC)
    return LLMProviderIntegration(
        id="integration-1",
        workspace_id="workspace-1",
        provider=LLMProvider.KIMI_OAUTH,
        name="Kimi subscription",
        config=KimiOAuthConfig(
            connection_method="device",
            status="connected",
            connected_at=now,
            last_refreshed_at=now,
            last_failed_at=None,
            last_failure_reason=None,
        ),
        enabled=True,
        created_at=now,
        updated_at=now,
    )


async def test_start_requires_integration_write_permission() -> None:
    """Reject device authorization before invoking the provider service."""
    service = AsyncMock(spec=KimiOAuthService)

    with pytest.raises(HTTPException) as caught:
        await start_device(member=_member(write=False), service=service)

    assert caught.value.status_code == 403
    service.start_device.assert_not_awaited()


async def test_start_response_contains_only_public_device_flow_fields() -> None:
    """Never expose device code, device ID, or token fields from start."""
    now = datetime.datetime.now(datetime.UTC)
    service = AsyncMock(spec=KimiOAuthService)
    service.start_device.return_value = Success(
        KimiOAuthDeviceStartOutput(
            session_id="session-1",
            user_code="ABCD-EFGH",
            verification_uri="https://auth.kimi.com/device?user_code=ABCD-EFGH",
            interval_seconds=5,
            expires_at=now + datetime.timedelta(minutes=15),
        )
    )

    response = await start_device(member=_member(), service=service)
    payload = response.model_dump(mode="json")

    assert payload["session_id"] == "session-1"
    assert payload["user_code"] == "ABCD-EFGH"
    serialized = str(payload).lower()
    for secret_name in (
        "device_code",
        "device_id",
        "access_token",
        "refresh_token",
    ):
        assert secret_name not in serialized


async def test_connected_poll_queues_catalog_sync_and_redacts_secrets() -> None:
    """Return the public integration and queue initial catalog sync once."""
    service = AsyncMock(spec=KimiOAuthService)
    service.poll_device.return_value = Success(
        KimiOAuthDeviceStatusOutput(
            session_id="session-1",
            status=KimiOAuthSessionStatus.CONNECTED,
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
    payload = response.model_dump(mode="json")

    assert payload["integration"]["provider"] == "kimi_oauth"
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].kwargs["integration_id"] == "integration-1"
    serialized = str(payload).lower()
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "device_id" not in serialized


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (SessionNotFound(session_id="missing"), 404),
        (InvalidSession(reason="private invalid detail"), 400),
        (ProviderRejected(reason="private rejection detail"), 400),
        (SessionTransitionFailed(session_id="conflict"), 409),
    ],
)
async def test_controlled_errors_map_to_public_status(
    error: SessionNotFound
    | InvalidSession
    | ProviderRejected
    | SessionTransitionFailed,
    status_code: int,
) -> None:
    """Map controlled service failures without exposing provider details."""
    service = AsyncMock(spec=KimiOAuthService)
    service.start_device.return_value = Failure(error)

    with pytest.raises(HTTPException) as caught:
        await start_device(member=_member(), service=service)

    assert caught.value.status_code == status_code
    assert "private" not in str(caught.value.detail).lower()


async def test_provider_unavailable_propagates_as_internal_failure() -> None:
    """Let the common server handler own unexpected provider outages."""
    service = AsyncMock(spec=KimiOAuthService)
    service.start_device.return_value = Failure(
        ProviderUnavailable(reason="private upstream detail")
    )

    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        await start_device(member=_member(), service=service)


def test_routes_are_mounted_under_the_kimi_device_flow_paths() -> None:
    """Keep the generated-client paths stable."""
    paths = {route.path for route in router.routes if isinstance(route, APIRoute)}

    assert "/workspaces/{handle}/kimi-oauth/device/start" in paths
    assert "/workspaces/{handle}/kimi-oauth/device/{session_id}" in paths
