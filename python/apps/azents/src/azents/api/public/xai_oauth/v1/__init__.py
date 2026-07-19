"""xAI OAuth v1 Public API routes."""

import logging
from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.permissions import Permissions
from azents.core.llm_catalog_sync import IntegrationCatalogSyncTrigger
from azents.services.llm_catalog import IntegrationCatalogProjectionService
from azents.services.xai_oauth import XaiOAuthService
from azents.services.xai_oauth.data import (
    InvalidSession,
    ProviderEntitlementDenied,
    ProviderPending,
    ProviderRejected,
    ProviderSlowDown,
    ProviderUnavailable,
    SessionNotFound,
    SessionTransitionFailed,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    XaiOAuthDeviceStartResponse,
    XaiOAuthDeviceStatusResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_write_permission(member: WorkspaceMember) -> None:
    """Check LLM integration write permission."""
    if not member.has_permission(Permissions.LLM_INTEGRATIONS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LLM integration write permission is required.",
        )


@router.post("/workspaces/{handle}/xai-oauth/device/start")
async def start_device(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[XaiOAuthService, Depends()],
) -> XaiOAuthDeviceStartResponse:
    """Start xAI OAuth device flow."""
    _require_write_permission(member)
    result = await service.start_device(
        workspace_id=member.workspace_id,
        user_id=member.user_id,
    )
    match result:
        case Success(value):
            return XaiOAuthDeviceStartResponse.convert_from(value)
        case Failure(error):
            _raise_oauth_error(error)
            raise AssertionError("unreachable")
        case _:
            assert_never(result)


@router.get("/workspaces/{handle}/xai-oauth/device/{session_id}")
async def poll_device(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[XaiOAuthService, Depends()],
    catalog_sync_service: Annotated[IntegrationCatalogProjectionService, Depends()],
    background_tasks: BackgroundTasks,
    *,
    session_id: str,
) -> XaiOAuthDeviceStatusResponse:
    """Poll xAI OAuth device flow status once."""
    _require_write_permission(member)
    result = await service.poll_device(
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        session_id=session_id,
    )
    match result:
        case Success(value):
            if value.integration is not None:
                background_tasks.add_task(
                    _run_initial_catalog_sync,
                    service=catalog_sync_service,
                    integration_id=value.integration.id,
                    workspace_id=member.workspace_id,
                )
            return XaiOAuthDeviceStatusResponse.convert_from(value)
        case Failure(error):
            _raise_oauth_error(error)
            raise AssertionError("unreachable")
        case _:
            assert_never(result)


@router.delete("/workspaces/{handle}/xai-oauth/device/{session_id}")
async def cancel_device(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[XaiOAuthService, Depends()],
    *,
    session_id: str,
) -> XaiOAuthDeviceStatusResponse:
    """Cancel xAI OAuth device flow."""
    _require_write_permission(member)
    result = await service.cancel_device(
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        session_id=session_id,
    )
    match result:
        case Success(value):
            return XaiOAuthDeviceStatusResponse.convert_from(value)
        case Failure(error):
            _raise_oauth_error(error)
            raise AssertionError("unreachable")
        case _:
            assert_never(result)


async def _run_initial_catalog_sync(
    *,
    service: IntegrationCatalogProjectionService,
    integration_id: str,
    workspace_id: str,
) -> None:
    """Run initial xAI catalog sync after OAuth connection."""
    try:
        await service.sync_integration_catalog(
            integration_id=integration_id,
            workspace_id=workspace_id,
            trigger=IntegrationCatalogSyncTrigger.CREATE,
        )
    except Exception:
        logger.exception(
            "Unexpected xAI catalog initial sync failure.",
            extra={"integration_id": integration_id, "workspace_id": workspace_id},
        )


def _raise_oauth_error(error: object) -> None:
    """Convert service errors to HTTPException."""
    match error:
        case SessionNotFound():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="OAuth session was not found.",
            )
        case InvalidSession():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth session is invalid or expired.",
            )
        case ProviderPending() | ProviderSlowDown():
            raise HTTPException(
                status_code=status.HTTP_202_ACCEPTED,
                detail="xAI authorization is still pending.",
            )
        case ProviderRejected():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="xAI OAuth provider rejected the request.",
            )
        case ProviderEntitlementDenied():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "xAI accepted OAuth login, but this account is not entitled "
                    "to the OAuth API surface. Try a different xAI tier or use "
                    "an xAI API key provider."
                ),
            )
        case ProviderUnavailable():
            raise RuntimeError("xAI OAuth provider is temporarily unavailable.")
        case SessionTransitionFailed():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="OAuth session state could not be updated.",
            )
        case _:
            raise RuntimeError("Unexpected OAuth error.")


def mount(mounter: RouteMounter) -> None:
    """Mount xAI OAuth v1 routes."""
    mounter(
        router,
        prefix="/llm-provider-integration/v1",
        tag="xAI OAuth v1",
        description=dedent(
            """
            xAI OAuth API (Public)

            Starts and completes xAI OAuth device-code connections.
            Tokens and authorization codes are never returned in API responses.
            """
        ),
    )
