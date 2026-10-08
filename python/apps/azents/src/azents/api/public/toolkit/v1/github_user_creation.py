"""Ownership-symmetric GitHub authorization before Toolkit creation."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from azents.api.public.toolkit.v1.data import ToolkitConfigCreateRequest
from azents.api.public.toolkit.v1.github_user import (
    GitHubUserAttemptRequest,
    GitHubUserExchangeRequest,
    Member,
    _management_errors,
)
from azents.api.public.toolkit.v1.github_user_validation import GitHubUserRoute
from azents.core.auth.deps import WorkspaceMember
from azents.core.github_user_creation import GitHubUserCreationSubject
from azents.services.github_user_oauth.creation import GitHubUserCreationService
from azents.services.github_user_oauth.data import (
    GitHubUserConnectOutput,
    GitHubUserCreatedOutput,
    GitHubUserCreationReview,
)
from azents.services.toolkit.data import ToolkitCreateInput

router = APIRouter(route_class=GitHubUserRoute)
Creation = Annotated[GitHubUserCreationService, Depends()]


def _subject(
    member: WorkspaceMember, agent_id: str | None
) -> GitHubUserCreationSubject:
    return GitHubUserCreationSubject(
        member.user_id, member.session_id, member.workspace_id, agent_id
    )


def _input(
    body: ToolkitConfigCreateRequest, member: WorkspaceMember
) -> ToolkitCreateInput:
    return ToolkitCreateInput(workspace_id=member.workspace_id, **body.model_dump())


@router.post("/workspaces/{handle}/github-user-creations/connect")
async def shared_creation_connect(
    member: Member, service: Creation, body: ToolkitConfigCreateRequest, *, handle: str
) -> GitHubUserConnectOutput:
    """Authorize desired settings without creating a saved Toolkit."""
    del handle
    with _management_errors():
        return await service.connect(_subject(member, None), _input(body, member))


@router.post("/workspaces/{handle}/agents/{agent_id}/github-user-creations/connect")
async def agent_creation_connect(
    member: Member,
    service: Creation,
    body: ToolkitConfigCreateRequest,
    *,
    handle: str,
    agent_id: str,
) -> GitHubUserConnectOutput:
    """Start unpublished creation within exact Agent management authority."""
    del handle
    with _management_errors():
        return await service.connect(_subject(member, agent_id), _input(body, member))


@router.post("/workspaces/{handle}/github-user-creations/exchange")
async def shared_creation_exchange(
    member: Member, service: Creation, body: GitHubUserExchangeRequest, *, handle: str
) -> GitHubUserCreationReview:
    """Exchange once and stage identity without publishing configuration."""
    del handle
    with _management_errors():
        return await service.exchange(
            _subject(member, None), code=body.code, state=body.state
        )


@router.post("/workspaces/{handle}/agents/{agent_id}/github-user-creations/exchange")
async def agent_creation_exchange(
    member: Member,
    service: Creation,
    body: GitHubUserExchangeRequest,
    *,
    handle: str,
    agent_id: str,
) -> GitHubUserCreationReview:
    """Review only the initiating Agent-owned creation context."""
    del handle
    with _management_errors():
        return await service.exchange(
            _subject(member, agent_id), code=body.code, state=body.state
        )


@router.get("/workspaces/{handle}/github-user-creations/{attempt_id}")
async def shared_creation_review(
    member: Member, service: Creation, *, handle: str, attempt_id: str
) -> GitHubUserCreationReview:
    """Read desired nonsecret settings and verified account for confirmation."""
    del handle
    with _management_errors():
        return await service.review(_subject(member, None), attempt_id)


@router.get("/workspaces/{handle}/agents/{agent_id}/github-user-creations/{attempt_id}")
async def agent_creation_review(
    member: Member, service: Creation, *, handle: str, agent_id: str, attempt_id: str
) -> GitHubUserCreationReview:
    """Resume only this initiating Agent creation."""
    del handle
    with _management_errors():
        return await service.review(_subject(member, agent_id), attempt_id)


@router.post("/workspaces/{handle}/github-user-creations/confirm")
async def shared_creation_confirm(
    member: Member, service: Creation, body: GitHubUserAttemptRequest, *, handle: str
) -> GitHubUserCreatedOutput:
    """Atomically create a shared Toolkit and its confirmed account."""
    del handle
    with _management_errors():
        return await service.confirm(_subject(member, None), body.attempt_id)


@router.post("/workspaces/{handle}/agents/{agent_id}/github-user-creations/confirm")
async def agent_creation_confirm(
    member: Member,
    service: Creation,
    body: GitHubUserAttemptRequest,
    *,
    handle: str,
    agent_id: str,
) -> GitHubUserCreatedOutput:
    """Publish Toolkit, namespace and current account together."""
    del handle
    with _management_errors():
        return await service.confirm(_subject(member, agent_id), body.attempt_id)


@router.delete(
    "/workspaces/{handle}/github-user-creations/{attempt_id}",
    status_code=204,
    response_class=Response,
)
async def shared_creation_cancel(
    member: Member, service: Creation, *, handle: str, attempt_id: str
) -> None:
    """Cancel unpublished creation and await exact fail-open token cleanup."""
    del handle
    with _management_errors():
        await service.cancel(_subject(member, None), attempt_id)


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/github-user-creations/{attempt_id}",
    status_code=204,
    response_class=Response,
)
async def agent_creation_cancel(
    member: Member, service: Creation, *, handle: str, agent_id: str, attempt_id: str
) -> None:
    """Cancel only this Agent's unpublished creation."""
    del handle
    with _management_errors():
        await service.cancel(_subject(member, agent_id), attempt_id)
