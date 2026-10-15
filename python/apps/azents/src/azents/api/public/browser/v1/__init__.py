"""Authenticated concrete Session Browser projection and page closure REST API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from azents.api.public.browser.v1.data import (
    BrowserClosePageRequest,
    BrowserCreatePageRequest,
    BrowserCreatePageResponse,
    BrowserProjectionResponse,
)
from azents.api.public.browser.v1.websocket import router as websocket_router
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.services.runtime_browser.data import (
    RuntimeBrowserRequestError,
    RuntimeBrowserResource,
)
from azents.services.runtime_browser.deps import get_runtime_browser_service
from azents.services.runtime_browser.service import RuntimeBrowserService
from azents.utils.fastapi.route import RouteMounter

router = APIRouter()
router.include_router(websocket_router)


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}",
    operation_id="browser_v1_get_browser_projection",
    response_model=BrowserProjectionResponse,
)
async def get_browser_projection(
    handle: str,
    agent_id: str,
    session_id: str,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeBrowserService, Depends(get_runtime_browser_service)],
) -> BrowserProjectionResponse:
    """List authorized current Browser tasks without starting any Runtime."""
    try:
        result = await service.projection(
            user_id=member.user_id,
            authentication_session_id=member.session_id,
            resource=RuntimeBrowserResource(handle, agent_id, session_id),
        )
    except RuntimeBrowserRequestError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
            headers={"WWW-Authenticate": "Bearer"}
            if error.status_code == 401
            else None,
        ) from None
    return BrowserProjectionResponse.convert_from(result)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/pages/{page_id}/close",
    operation_id="browser_v1_close_browser_page",
    response_model=BrowserProjectionResponse,
)
async def close_browser_page(
    handle: str,
    agent_id: str,
    session_id: str,
    page_id: Annotated[str, Path(min_length=1, max_length=200)],
    body: BrowserClosePageRequest,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeBrowserService, Depends(get_runtime_browser_service)],
) -> BrowserProjectionResponse:
    """Close only the exact current page under directing Session authority."""
    try:
        result = await service.close_page(
            user_id=member.user_id,
            authentication_session_id=member.session_id,
            resource=RuntimeBrowserResource(handle, agent_id, session_id),
            task_id=body.task_id,
            page_id=page_id,
            resource_incarnation=body.resource_incarnation,
        )
    except RuntimeBrowserRequestError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
            headers={"WWW-Authenticate": "Bearer"}
            if error.status_code == 401
            else None,
        ) from None
    return BrowserProjectionResponse.convert_from(result)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/pages",
    operation_id="browser_v1_create_browser_page",
    response_model=BrowserCreatePageResponse,
)
async def create_browser_page(
    handle: str,
    agent_id: str,
    session_id: str,
    body: BrowserCreatePageRequest,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeBrowserService, Depends(get_runtime_browser_service)],
) -> BrowserCreatePageResponse:
    """Create a blank tab using the current directing Session authority."""
    try:
        result = await service.create_page(
            user_id=member.user_id,
            authentication_session_id=member.session_id,
            resource=RuntimeBrowserResource(handle, agent_id, session_id),
        )
    except RuntimeBrowserRequestError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
            headers={"WWW-Authenticate": "Bearer"}
            if error.status_code == 401
            else None,
        ) from None
    return BrowserCreatePageResponse.convert_from(result)


def mount(mounter: RouteMounter) -> None:
    mounter(
        router,
        prefix="/browser/v1",
        tag="Browser v1",
        description=(
            "Authorized current Session Browser projection and exact page closure."
        ),
    )
