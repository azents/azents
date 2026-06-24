"""GitHub PAT v1 Public API.

Workspace user GitHub PAT register/read/delete endpoints.
"""

import logging
from textwrap import dedent
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.services.github_pat import GitHubPATService
from azents.utils.fastapi.route import RouteMounter

from .data import (
    PATStatusResponse,
    RegisterPATRequest,
    RegisterPATResponse,
    SetupStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/workspaces/{handle}/github-pat",
    status_code=status.HTTP_201_CREATED,
)
async def register_pat(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[GitHubPATService, Depends()],
    *,
    request_body: RegisterPATRequest,
) -> RegisterPATResponse:
    """Register a GitHub PAT.

    Validate the token with GitHub GET /user, then encrypt and store it.
    """
    pat = await service.verify_and_register(
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        token=request_body.token,
    )

    if pat is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid GitHub token",
        )

    return RegisterPATResponse(
        github_username=pat.github_username or "",
        expires_at=pat.expires_at,
    )


@router.get("/workspaces/{handle}/github-pat")
async def get_pat_status(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[GitHubPATService, Depends()],
) -> PATStatusResponse:
    """Get GitHub PAT status."""
    pat_status = await service.get_status(member.workspace_id, member.user_id)

    return PATStatusResponse(
        registered=pat_status.registered,
        github_username=pat_status.github_username,
        display_hint=pat_status.display_hint,
        expires_at=pat_status.expires_at,
    )


@router.delete(
    "/workspaces/{handle}/github-pat",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_pat(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[GitHubPATService, Depends()],
) -> None:
    """Delete a GitHub PAT."""
    await service.delete(member.workspace_id, member.user_id)


@router.get("/workspaces/{handle}/github-pat/setup-status")
async def get_setup_status(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[GitHubPATService, Depends()],
) -> SetupStatusResponse:
    """Get status for the settings page.

    Returns whether a PAT is registered.
    """
    pat_status = await service.get_status(member.workspace_id, member.user_id)

    return SetupStatusResponse(
        platform_linked=True,
        pat_registered=pat_status.registered,
        github_username=pat_status.github_username,
    )


def mount(mounter: RouteMounter) -> None:
    """Mount GitHub PAT v1 routes."""
    mounter(
        router,
        prefix="/github-pat/v1",
        tag="GitHub PAT v1",
        description=dedent(
            """
            GitHub PAT API (Public)

            Workspace user GitHub PAT register/read/delete endpoints.
            """
        ),
    )
