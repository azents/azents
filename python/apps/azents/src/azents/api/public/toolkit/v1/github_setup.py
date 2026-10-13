"""Ownership-symmetric unpublished GitHub setup observations."""

from typing import Annotated

from fastapi import APIRouter, Depends

from azents.api.public.toolkit.v1.github_user import Member, _management_errors
from azents.api.public.toolkit.v1.github_user_creation import _subject
from azents.api.public.toolkit.v1.github_user_validation import GitHubUserRoute
from azents.core.github_setup import (
    GitHubSetupAppOutput,
    GitHubSetupVerificationOutput,
    GitHubSetupVerificationRequest,
)
from azents.services.github_user_oauth.setup import GitHubSetupService

router = APIRouter(route_class=GitHubUserRoute)
Setup = Annotated[GitHubSetupService, Depends()]


@router.get("/workspaces/{handle}/github/setup-app")
async def shared_setup_app(
    member: Member, service: Setup, *, handle: str
) -> GitHubSetupAppOutput:
    """Observe current Platform display metadata after exact shared admission."""
    del handle
    with _management_errors():
        return await service.app(_subject(member, None))


@router.get("/workspaces/{handle}/agents/{agent_id}/github/setup-app")
async def agent_setup_app(
    member: Member, service: Setup, *, handle: str, agent_id: str
) -> GitHubSetupAppOutput:
    """Observe current Platform App only within the exact Agent management scope."""
    del handle
    with _management_errors():
        return await service.app(_subject(member, agent_id))


@router.post("/workspaces/{handle}/github/setup-verification")
async def shared_setup_verification(
    member: Member,
    service: Setup,
    body: GitHubSetupVerificationRequest,
    *,
    handle: str,
) -> GitHubSetupVerificationOutput:
    """Verify unsaved execution identity without creating an executable Toolkit."""
    del handle
    with _management_errors():
        return await service.verify(_subject(member, None), body)


@router.post("/workspaces/{handle}/agents/{agent_id}/github/setup-verification")
async def agent_setup_verification(
    member: Member,
    service: Setup,
    body: GitHubSetupVerificationRequest,
    *,
    handle: str,
    agent_id: str,
) -> GitHubSetupVerificationOutput:
    """Verify unsaved credentials only within this exact managed Agent."""
    del handle
    with _management_errors():
        return await service.verify(_subject(member, agent_id), body)
