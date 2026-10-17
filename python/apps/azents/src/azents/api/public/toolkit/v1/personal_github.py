"""Exact account-owned GitHub connection setup through the common grant lifecycle."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.github_setup import (
    GitHubSetupAppOutput,
    GitHubSetupVerificationOutput,
    GitHubSetupVerificationRequest,
)
from azents.core.github_user_auth import GitHubUserAccessPage
from azents.core.github_user_creation import (
    GitHubPersonalCreationSubject,
    GitHubUserCreationConfirmRequest,
)
from azents.core.github_user_oauth import (
    GitHubPersonalRequester,
    GitHubUserConnectionSummary,
)
from azents.core.personal_toolkit import PersonalToolkitManager
from azents.core.toolkit_ownership import ToolkitOwnerKind, UserToolkitOwner
from azents.services.github_user_oauth.creation import GitHubUserCreationService
from azents.services.github_user_oauth.data import (
    GitHubSetupAvailability,
    GitHubUserCandidateSummary,
    GitHubUserConnectOutput,
    GitHubUserCreatedOutput,
    GitHubUserCreationReview,
    GitHubUserStatusOutput,
)
from azents.services.github_user_oauth.personal_installations import (
    PersonalGitHubInstallationsService,
)
from azents.services.github_user_oauth.service import GitHubUserOAuthService
from azents.services.github_user_oauth.setup import GitHubSetupService

from .github_user import (
    GitHubUserAttemptRequest,
    GitHubUserExchangeRequest,
    _management_errors,
)
from .github_user_validation import GitHubUserRoute
from .oauth import (
    GitHubInstallationItem,
    GitHubPlatformInstallationsResponse,
    GitHubPlatformInstallUrlResponse,
    GitHubPlatformOAuthUrlResponse,
)
from .personal import PersonalToolkitCreateRequest
from .personal_oauth import PersonalOAuthExchangeRequest, _oauth_errors

router = APIRouter(prefix="/workspaces/{handle}", route_class=GitHubUserRoute)
Account = Annotated[WorkspaceMember, Depends(get_workspace_member)]
Service = Annotated[GitHubUserOAuthService, Depends(GitHubUserOAuthService)]
Creation = Annotated[GitHubUserCreationService, Depends(GitHubUserCreationService)]
Setup = Annotated[GitHubSetupService, Depends(GitHubSetupService)]
Installations = Annotated[
    PersonalGitHubInstallationsService, Depends(PersonalGitHubInstallationsService)
]


@router.get("/personal/github/platform-install-url")
async def personal_github_install_url(
    account: Account,
    service: Installations,
) -> GitHubPlatformInstallUrlResponse:
    """Open the same Platform App installation page after exact account admission."""
    with _oauth_errors():
        value = await service.install_url(
            PersonalToolkitManager(
                account.user_id, account.session_id, account.workspace_id
            )
        )
    return GitHubPlatformInstallUrlResponse(install_url=value)


@router.get("/personal/github/platform-oauth-url")
async def personal_github_installation_oauth_url(
    account: Account,
    service: Installations,
) -> GitHubPlatformOAuthUrlResponse:
    """Start owner/Auth Session-bound Platform installation acquisition."""
    with _oauth_errors():
        value = await service.oauth_url(
            PersonalToolkitManager(
                account.user_id, account.session_id, account.workspace_id
            )
        )
    return GitHubPlatformOAuthUrlResponse(oauth_url=value)


@router.post("/personal/github/platform-installations")
async def personal_github_sync_installations(
    account: Account,
    service: Installations,
    body: PersonalOAuthExchangeRequest,
) -> GitHubPlatformInstallationsResponse:
    """Publish the current owner's installation inventory, with no Toolkit creation."""
    with _oauth_errors():
        values = await service.sync(
            PersonalToolkitManager(
                account.user_id, account.session_id, account.workspace_id
            ),
            code=body.code,
            state=body.state,
        )
    return GitHubPlatformInstallationsResponse(
        installations=[
            GitHubInstallationItem(
                id=value.id,
                account_login=value.account_login,
                account_type=value.account_type,
                account_avatar_url=value.account_avatar_url,
            )
            for value in values
        ]
    )


def _creation_subject(account: WorkspaceMember) -> GitHubPersonalCreationSubject:
    return GitHubPersonalCreationSubject(
        user_id=account.user_id,
        session_id=account.session_id,
        owner=UserToolkitOwner(
            kind=ToolkitOwnerKind.USER,
            user_id=account.user_id,
            workspace_id=account.workspace_id,
        ),
    )


@router.get("/personal/github/setup-app")
async def personal_github_setup_app(
    account: Account, service: Setup
) -> GitHubSetupAppOutput:
    """Observe the current Platform App after current-account personal admission."""
    with _management_errors():
        return await service.app(_creation_subject(account))


@router.post("/personal/github/setup-verification")
async def personal_github_setup_verify(
    account: Account,
    service: Setup,
    body: GitHubSetupVerificationRequest,
) -> GitHubSetupVerificationOutput:
    """Verify ordinary PAT/provided-App/Platform-App modes without publication."""
    with _management_errors():
        return await service.verify(_creation_subject(account), body)


@router.post("/personal/github-user-creations/connect")
async def personal_github_creation_connect(
    account: Account,
    service: Creation,
    body: PersonalToolkitCreateRequest,
) -> GitHubUserConnectOutput:
    """Authorize common GitHub settings before creating a personal Toolkit."""
    with _management_errors():
        return await service.connect(_creation_subject(account), body)


@router.post("/personal/github-user-creations/exchange")
async def personal_github_creation_exchange(
    account: Account,
    service: Creation,
    body: GitHubUserExchangeRequest,
) -> GitHubUserCreationReview:
    """Stage verified account identity under exact personal setup authority."""
    with _management_errors():
        return await service.exchange(
            _creation_subject(account),
            code=body.code,
            state=body.state,
        )


@router.get("/personal/github-user-creations/{attempt_id}")
async def personal_github_creation_review(
    account: Account,
    service: Creation,
    attempt_id: str,
) -> GitHubUserCreationReview:
    """Read the common reviewed settings with explicit personal sharing scope."""
    with _management_errors():
        return await service.review(_creation_subject(account), attempt_id)


@router.get("/personal/github-user-creations/{attempt_id}/app")
async def personal_github_creation_app(
    account: Account,
    service: Creation,
    attempt_id: str,
) -> GitHubSetupAppOutput:
    """Observe actual selected App metadata without publishing the connection."""
    with _management_errors():
        return await service.app(_creation_subject(account), attempt_id)


@router.post("/personal/github-user-creations/confirm")
async def personal_github_creation_confirm(
    account: Account,
    service: Creation,
    body: GitHubUserCreationConfirmRequest,
) -> GitHubUserCreatedOutput:
    """Publish canonical personal ownership after reviewed confirmation."""
    with _management_errors():
        return await service.confirm(
            _creation_subject(account),
            body.attempt_id,
            body.settings,
        )


@router.delete("/personal/github-user-creations/{attempt_id}", status_code=204)
async def personal_github_creation_cancel(
    account: Account,
    service: Creation,
    attempt_id: str,
) -> Response:
    """Cancel only the initiating owner's unpublished personal credentials."""
    with _management_errors():
        await service.cancel(_creation_subject(account), attempt_id)
    return Response(status_code=204)


def _requester(account: WorkspaceMember, toolkit_id: str) -> GitHubPersonalRequester:
    return GitHubPersonalRequester(
        user_id=account.user_id,
        session_id=account.session_id,
        toolkit_id=toolkit_id,
        owner=UserToolkitOwner(
            kind=ToolkitOwnerKind.USER,
            user_id=account.user_id,
            workspace_id=account.workspace_id,
        ),
    )


@router.get("/personal/github/setup-availability")
async def personal_github_availability(
    account: Account, service: Service
) -> GitHubSetupAvailability:
    """Use the common auth-mode readiness without requiring a Workspace membership."""
    with _management_errors():
        return await service.personal_availability(
            user_id=account.user_id,
            session_id=account.session_id,
            workspace_id=account.workspace_id,
        )


@router.post("/personal-toolkit-configs/{toolkit_id}/github-user/connect")
async def personal_github_connect(
    account: Account, service: Service, toolkit_id: str
) -> GitHubUserConnectOutput:
    """Start exact-owner reviewed reconnect without replacing current credentials."""
    with _management_errors():
        return await service.connect(_requester(account, toolkit_id))


@router.post("/personal-toolkit-configs/{toolkit_id}/github-user/exchange")
async def personal_github_exchange(
    account: Account, service: Service, toolkit_id: str, body: GitHubUserExchangeRequest
) -> GitHubUserCandidateSummary:
    """Exchange only the initiating personal account and Auth Session's attempt."""
    with _management_errors():
        return await service.exchange(
            _requester(account, toolkit_id), code=body.code, state=body.state
        )


@router.get("/personal-toolkit-configs/{toolkit_id}/github-user/review")
async def personal_github_review(
    account: Account, service: Service, toolkit_id: str, attempt_id: str
) -> GitHubUserCandidateSummary:
    """Expose the same verified account metadata and explicit personal sharing scope."""
    with _management_errors():
        return await service.review(
            _requester(account, toolkit_id), attempt_id=attempt_id
        )


@router.post("/personal-toolkit-configs/{toolkit_id}/github-user/confirm")
async def personal_github_confirm(
    account: Account, service: Service, toolkit_id: str, body: GitHubUserAttemptRequest
) -> GitHubUserConnectionSummary:
    """Activate the reviewed personal grant using existing replacement checks."""
    with _management_errors():
        return await service.confirm(
            _requester(account, toolkit_id), attempt_id=body.attempt_id
        )


@router.delete(
    "/personal-toolkit-configs/{toolkit_id}/github-user/attempt", status_code=204
)
async def personal_github_cancel(
    account: Account, service: Service, toolkit_id: str, body: GitHubUserAttemptRequest
) -> Response:
    """Cancel the exact owner's unpublished setup and clean up its candidate."""
    with _management_errors():
        await service.cancel(
            _requester(account, toolkit_id), attempt_id=body.attempt_id
        )
    return Response(status_code=204)


@router.get("/personal-toolkit-configs/{toolkit_id}/github-user/connection")
async def personal_github_status(
    account: Account, service: Service, toolkit_id: str
) -> GitHubUserStatusOutput:
    """Read current exact-owner grant identity without credential material."""
    with _management_errors():
        return await service.status(_requester(account, toolkit_id))


@router.get("/personal-toolkit-configs/{toolkit_id}/github-user/access")
async def personal_github_access(
    account: Account,
    service: Service,
    toolkit_id: str,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
) -> GitHubUserAccessPage:
    """Observe the exact owner's bounded account/App access through common checks."""
    with _management_errors():
        return await service.access(_requester(account, toolkit_id), cursor=cursor)


@router.delete(
    "/personal-toolkit-configs/{toolkit_id}/github-user/connection", status_code=204
)
async def personal_github_disconnect(
    account: Account, service: Service, toolkit_id: str
) -> Response:
    """Remove local personal execution authority before bounded Provider cleanup."""
    with _management_errors():
        await service.disconnect(_requester(account, toolkit_id))
    return Response(status_code=204)
