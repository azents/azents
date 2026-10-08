"""Ownership-symmetric GitHub user-account setup and cleanup endpoints."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, assert_never

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from azents.api.public.toolkit.v1.github_user_validation import GitHubUserRoute
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.github_user_auth import GitHubUserAccessPage, GitHubUserProviderError
from azents.core.github_user_oauth import (
    GitHubUserConnectionSummary,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRequester,
)
from azents.services.github_user_oauth.data import (
    GitHubSetupAvailability,
    GitHubUserCandidateSummary,
    GitHubUserConnectOutput,
    GitHubUserStatusOutput,
)
from azents.services.github_user_oauth.service import GitHubUserOAuthService

router = APIRouter(route_class=GitHubUserRoute)


class GitHubUserExchangeRequest(BaseModel):
    """Transient provider callback inputs excluded from model representations."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    code: str = Field(min_length=1, max_length=4096, repr=False)
    state: str = Field(min_length=1, max_length=4096, repr=False)


class GitHubUserAttemptRequest(BaseModel):
    """Exact local attempt for confirm or cancellation."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    attempt_id: str = Field(min_length=1, max_length=64)


@contextmanager
def _management_errors() -> Iterator[None]:
    """Map expected management rejections, never return provider failures as success."""
    try:
        yield
    except GitHubUserOAuthError as error:
        match error.code:
            case GitHubUserErrorCode.AUTHORITY:
                status = 403
            case GitHubUserErrorCode.NOT_FOUND:
                status = 404
            case GitHubUserErrorCode.STALE:
                status = 409
            case GitHubUserErrorCode.INVALID:
                status = 400
            case _:
                assert_never(error.code)
        raise HTTPException(
            status_code=status,
            detail={"code": error.code.value, "message": str(error)},
        ) from None
    except GitHubUserProviderError as error:
        if error.reason in ("authentication", "target_denied"):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "github_authorization_failed",
                    "message": "GitHub authorization failed. Check the selected App "
                    "and account access or reauthorize the Toolkit.",
                },
            ) from None
        raise


def _requester(
    member: WorkspaceMember, *, agent_id: str | None, toolkit_id: str
) -> GitHubUserRequester:
    """Bind authenticated request identity; never accept it from request JSON."""
    return GitHubUserRequester(
        user_id=member.user_id,
        session_id=member.session_id,
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        toolkit_id=toolkit_id,
    )


Member = Annotated[WorkspaceMember, Depends(get_workspace_member)]
Service = Annotated[GitHubUserOAuthService, Depends(GitHubUserOAuthService)]


@router.get("/workspaces/{handle}/github/setup-availability")
async def shared_setup_availability(
    member: Member, service: Service, *, handle: str
) -> GitHubSetupAvailability:
    """Return local Platform registration availability for shared setup."""
    del handle
    with _management_errors():
        return await service.availability(
            user_id=member.user_id,
            session_id=member.session_id,
            workspace_id=member.workspace_id,
            agent_id=None,
        )


@router.get("/workspaces/{handle}/agents/{agent_id}/github/setup-availability")
async def agent_setup_availability(
    member: Member, service: Service, *, handle: str, agent_id: str
) -> GitHubSetupAvailability:
    """Return local registration availability only to an Agent manager."""
    del handle
    with _management_errors():
        return await service.availability(
            user_id=member.user_id,
            session_id=member.session_id,
            workspace_id=member.workspace_id,
            agent_id=agent_id,
        )


@router.post("/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/connect")
async def shared_connect(
    member: Member, service: Service, *, handle: str, toolkit_id: str
) -> GitHubUserConnectOutput:
    """Start one bound shared-Toolkit authorization without replacing credentials."""
    del handle
    with _management_errors():
        return await service.connect(
            _requester(member, agent_id=None, toolkit_id=toolkit_id)
        )


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/connect"
)
async def agent_connect(
    member: Member, service: Service, *, handle: str, agent_id: str, toolkit_id: str
) -> GitHubUserConnectOutput:
    """Start setup for a Toolkit owned by this exact managed Agent."""
    del handle
    with _management_errors():
        return await service.connect(
            _requester(member, agent_id=agent_id, toolkit_id=toolkit_id)
        )


@router.post("/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/exchange")
async def shared_exchange(
    member: Member,
    service: Service,
    body: GitHubUserExchangeRequest,
    *,
    handle: str,
    toolkit_id: str,
) -> GitHubUserCandidateSummary:
    """Stage verified account identity for the same shared setup context."""
    del handle
    with _management_errors():
        return await service.exchange(
            _requester(member, agent_id=None, toolkit_id=toolkit_id),
            code=body.code,
            state=body.state,
        )


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/exchange"
)
async def agent_exchange(
    member: Member,
    service: Service,
    body: GitHubUserExchangeRequest,
    *,
    handle: str,
    agent_id: str,
    toolkit_id: str,
) -> GitHubUserCandidateSummary:
    """Consume one callback without changing the existing Agent-owned credential."""
    del handle
    with _management_errors():
        return await service.exchange(
            _requester(member, agent_id=agent_id, toolkit_id=toolkit_id),
            code=body.code,
            state=body.state,
        )


@router.get(
    "/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/attempts/{attempt_id}"
)
async def shared_review(
    member: Member,
    service: Service,
    *,
    handle: str,
    toolkit_id: str,
    attempt_id: str,
) -> GitHubUserCandidateSummary:
    """Read current review identity from the originating shared setup."""
    del handle
    with _management_errors():
        return await service.review(
            _requester(member, agent_id=None, toolkit_id=toolkit_id),
            attempt_id=attempt_id,
        )


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}"
    "/github-user/attempts/{attempt_id}"
)
async def agent_review(
    member: Member,
    service: Service,
    *,
    handle: str,
    agent_id: str,
    toolkit_id: str,
    attempt_id: str,
) -> GitHubUserCandidateSummary:
    """Read verified account/use scope after exact popup completion notification."""
    del handle
    with _management_errors():
        return await service.review(
            _requester(member, agent_id=agent_id, toolkit_id=toolkit_id),
            attempt_id=attempt_id,
        )


@router.post("/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/confirm")
async def shared_confirm(
    member: Member,
    service: Service,
    body: GitHubUserAttemptRequest,
    *,
    handle: str,
    toolkit_id: str,
) -> GitHubUserConnectionSummary:
    """Explicitly activate reviewed account and sharing scope."""
    del handle
    with _management_errors():
        return await service.confirm(
            _requester(member, agent_id=None, toolkit_id=toolkit_id),
            attempt_id=body.attempt_id,
        )


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/confirm"
)
async def agent_confirm(
    member: Member,
    service: Service,
    body: GitHubUserAttemptRequest,
    *,
    handle: str,
    agent_id: str,
    toolkit_id: str,
) -> GitHubUserConnectionSummary:
    """Confirm account replacement within the exact Agent-owned Toolkit."""
    del handle
    with _management_errors():
        return await service.confirm(
            _requester(member, agent_id=agent_id, toolkit_id=toolkit_id),
            attempt_id=body.attempt_id,
        )


@router.delete(
    "/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/attempt",
    status_code=204,
    response_class=Response,
)
async def shared_cancel(
    member: Member,
    service: Service,
    body: GitHubUserAttemptRequest,
    *,
    handle: str,
    toolkit_id: str,
) -> None:
    """Cancel the initiating shared setup and revoke any issued candidate."""
    del handle
    with _management_errors():
        await service.cancel(
            _requester(member, agent_id=None, toolkit_id=toolkit_id),
            attempt_id=body.attempt_id,
        )


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/attempt",
    status_code=204,
    response_class=Response,
)
async def agent_cancel(
    member: Member,
    service: Service,
    body: GitHubUserAttemptRequest,
    *,
    handle: str,
    agent_id: str,
    toolkit_id: str,
) -> None:
    """Cancel only this Agent-owned setup attempt."""
    del handle
    with _management_errors():
        await service.cancel(
            _requester(member, agent_id=agent_id, toolkit_id=toolkit_id),
            attempt_id=body.attempt_id,
        )


@router.delete(
    "/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/connection",
    status_code=204,
    response_class=Response,
)
async def shared_disconnect(
    member: Member, service: Service, *, handle: str, toolkit_id: str
) -> None:
    """Disconnect local shared use and attempt bounded token revocation."""
    del handle
    with _management_errors():
        await service.disconnect(
            _requester(member, agent_id=None, toolkit_id=toolkit_id)
        )


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/connection",
    status_code=204,
    response_class=Response,
)
async def agent_disconnect(
    member: Member, service: Service, *, handle: str, agent_id: str, toolkit_id: str
) -> None:
    """Disconnect the exact Agent-owned credential without affecting attachments."""
    del handle
    with _management_errors():
        await service.disconnect(
            _requester(member, agent_id=agent_id, toolkit_id=toolkit_id)
        )


@router.get("/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/status")
async def shared_status(
    member: Member, service: Service, *, handle: str, toolkit_id: str
) -> GitHubUserStatusOutput:
    """Return redacted saved identity without asserting provider cleanup."""
    del handle
    with _management_errors():
        return await service.status(
            _requester(member, agent_id=None, toolkit_id=toolkit_id)
        )


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/status"
)
async def agent_status(
    member: Member, service: Service, *, handle: str, agent_id: str, toolkit_id: str
) -> GitHubUserStatusOutput:
    """Return connection details only within exact Agent management scope."""
    del handle
    with _management_errors():
        return await service.status(
            _requester(member, agent_id=agent_id, toolkit_id=toolkit_id)
        )


@router.get("/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/access")
async def shared_access(
    member: Member,
    service: Service,
    *,
    handle: str,
    toolkit_id: str,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
) -> GitHubUserAccessPage:
    """Observe bounded personal and organization readiness for this account/App."""
    del handle
    with _management_errors():
        return await service.access(
            _requester(member, agent_id=None, toolkit_id=toolkit_id), cursor=cursor
        )


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/access"
)
async def agent_access(
    member: Member,
    service: Service,
    *,
    handle: str,
    agent_id: str,
    toolkit_id: str,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
) -> GitHubUserAccessPage:
    """Observe multi-owner readiness without granting participant list access."""
    del handle
    with _management_errors():
        return await service.access(
            _requester(member, agent_id=agent_id, toolkit_id=toolkit_id), cursor=cursor
        )
