"""Public SDK boundaries for persistent GitHub App user authorization."""

import asyncio
import base64
import binascii
import dataclasses
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from githubkit import BaseAuthStrategy, GitHub, OAuthAppAuthStrategy
from githubkit.exception import RequestError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
)

from azents.core.github_auth import GitHubClientFactory, create_github_client

_API_VERSION = "2022-11-28"
_PAGE_SIZE = 100
_REPOSITORY_REQUEST_BUDGET = 10
_MAX_PAGE = 100_000

ProviderFailureReason = Literal[
    "authentication", "target_denied", "provider_unavailable", "invalid_response"
]
TokenRejectionReason = Literal[
    "oauth_rejected", "invalid_response", "expiring_token", "invalid_token_type"
]


class GitHubUserProviderError(RuntimeError):
    """Sanitized provider failure without credential-bearing provider diagnostics."""

    def __init__(
        self, *, reason: ProviderFailureReason, status_code: int | None
    ) -> None:
        self.reason = reason
        self.status_code = status_code
        super().__init__("GitHub user authorization provider request failed: " + reason)


class GitHubUserTokenRejected(ValueError):
    """Rejected exchange with private cleanup material outside exception arguments."""

    def __init__(
        self, *, reason: TokenRejectionReason, issued_token: str | None
    ) -> None:
        self.reason = reason
        self.issued_token = issued_token
        super().__init__("GitHub user token response rejected: " + reason)


@dataclasses.dataclass(frozen=True)
class GitHubUserToken:
    """Accepted non-expiring credential; representation excludes token material."""

    access_token: str = dataclasses.field(repr=False)


@dataclasses.dataclass(frozen=True)
class GitHubUserIdentity:
    """Provider-verified account identity, separate from an Azents requester."""

    account_id: int
    login: str
    avatar_url: str | None


@dataclasses.dataclass(frozen=True)
class GitHubUserAppIdentity:
    """Authenticated App identity and its corresponding OAuth client registration."""

    app_id: int
    slug: str
    client_id: str


@dataclasses.dataclass(frozen=True)
class GitHubUserRepositoryPermissions:
    """Observed account permissions; absent provider facts remain unknown."""

    read: bool | None
    write: bool | None
    admin: bool | None


@dataclasses.dataclass(frozen=True)
class GitHubUserRepository:
    """Owner-qualified repository observation, not a local execution allowlist."""

    repository_id: int
    owner_login: str
    name: str
    full_name: str
    private: bool
    permissions: GitHubUserRepositoryPermissions


@dataclasses.dataclass(frozen=True)
class GitHubUserInstallation:
    """One bounded owner observation with independent repository readiness."""

    installation_id: int
    app_id: int
    account_login: str
    account_type: str
    account_avatar_url: str | None
    app_permissions: dict[str, str]
    repositories: tuple[GitHubUserRepository, ...]
    repositories_complete: bool
    failure_reason: ProviderFailureReason | None


@dataclasses.dataclass(frozen=True)
class GitHubUserAccessPage:
    """Bounded traversal result with an explicit continuation cursor."""

    installations: tuple[GitHubUserInstallation, ...]
    next_cursor: str | None


class _ProviderPayload(BaseModel):
    """Compatible provider extensions with private validation inputs."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _IssuedToken(_ProviderPayload):
    access_token: StrictStr | None = Field(default=None, repr=False)


class _OAuthEnvelope(_IssuedToken):
    token_type: StrictStr | None = None
    error: StrictStr | None = None
    expires_in: object = Field(default=None, repr=False)
    refresh_token: object = Field(default=None, repr=False)
    refresh_token_expires_in: object = Field(default=None, repr=False)


class _Identity(_ProviderPayload):
    id: StrictInt = Field(gt=0)
    login: StrictStr = Field(min_length=1)
    avatar_url: StrictStr | None = None


class _AppIdentity(_ProviderPayload):
    id: StrictInt = Field(gt=0)
    slug: StrictStr = Field(min_length=1)
    client_id: StrictStr = Field(min_length=1)


class _Account(_ProviderPayload):
    login: StrictStr = Field(min_length=1)
    type: StrictStr = Field(min_length=1)
    avatar_url: StrictStr | None = None


class _Installation(_ProviderPayload):
    id: StrictInt = Field(gt=0)
    app_id: StrictInt = Field(gt=0)
    account: _Account
    permissions: dict[StrictStr, StrictStr] = Field(default_factory=dict)


class _Installations(_ProviderPayload):
    installations: tuple[_Installation, ...] = Field(max_length=_PAGE_SIZE)


class _Owner(_ProviderPayload):
    login: StrictStr = Field(min_length=1)


class _Permissions(_ProviderPayload):
    pull: StrictBool | None = None
    push: StrictBool | None = None
    admin: StrictBool | None = None


class _Repository(_ProviderPayload):
    id: StrictInt = Field(gt=0)
    owner: _Owner
    name: StrictStr = Field(min_length=1)
    full_name: StrictStr = Field(min_length=1)
    private: StrictBool
    permissions: _Permissions | None = None


class _Repositories(_ProviderPayload):
    repositories: tuple[_Repository, ...] = Field(max_length=_PAGE_SIZE)


class _AccessCursor(BaseModel):
    """Local continuation coordinates; no provider URL is accepted as authority."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    installation_page: StrictInt = Field(ge=1, le=_MAX_PAGE)
    installation_index: StrictInt = Field(ge=0, lt=_PAGE_SIZE)
    repository_page: StrictInt = Field(ge=1, le=_MAX_PAGE)


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _API_VERSION,
    }


def _http_failure(status_code: int | None) -> GitHubUserProviderError:
    if status_code == 401:
        reason: ProviderFailureReason = "authentication"
    elif status_code in (403, 404):
        reason = "target_denied"
    else:
        reason = "provider_unavailable"
    return GitHubUserProviderError(reason=reason, status_code=status_code)


@asynccontextmanager
async def _client(
    auth: BaseAuthStrategy | None, client_factory: GitHubClientFactory
) -> AsyncIterator[GitHub[BaseAuthStrategy]]:
    """Own supported SDK lifetime and sanitize only expected provider failures."""
    try:
        async with client_factory(auth) as client:
            yield client
    except asyncio.CancelledError:
        raise
    except RequestError as error:
        if isinstance(error.exc, httpx.HTTPStatusError):
            raise _http_failure(error.exc.response.status_code) from None
        raise _http_failure(None) from None
    except httpx.HTTPStatusError as error:
        raise _http_failure(error.response.status_code) from None
    except httpx.HTTPError:
        raise _http_failure(None) from None
    except ValidationError, json.JSONDecodeError:
        raise GitHubUserProviderError(
            reason="invalid_response", status_code=None
        ) from None


def _decode_token(payload: object) -> GitHubUserToken:
    """Retain private issued-token cleanup material when its envelope is rejected."""
    try:
        issued = _IssuedToken.model_validate(payload).access_token
    except ValidationError:
        raise GitHubUserTokenRejected(
            reason="invalid_response", issued_token=None
        ) from None
    if issued is not None and not issued.strip():
        issued = None
    try:
        envelope = _OAuthEnvelope.model_validate(payload)
    except ValidationError:
        raise GitHubUserTokenRejected(
            reason="invalid_response", issued_token=issued
        ) from None
    if "error" in envelope.model_fields_set:
        raise GitHubUserTokenRejected(
            reason="oauth_rejected", issued_token=issued
        ) from None
    if issued is None:
        raise GitHubUserTokenRejected(
            reason="invalid_response", issued_token=None
        ) from None
    if envelope.model_fields_set.intersection(
        {"expires_in", "refresh_token", "refresh_token_expires_in"}
    ):
        raise GitHubUserTokenRejected(
            reason="expiring_token", issued_token=issued
        ) from None
    if envelope.token_type is None or envelope.token_type.casefold() != "bearer":
        raise GitHubUserTokenRejected(
            reason="invalid_token_type", issued_token=issued
        ) from None
    return GitHubUserToken(access_token=issued)


async def exchange_user_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    client_factory: GitHubClientFactory = create_github_client,
) -> GitHubUserToken:
    """Exchange once with PKCE through GitHubKit's public fixed-endpoint transport."""
    async with _client(None, client_factory) as client:
        response = await client.arequest(
            "POST",
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
        return _decode_token(response.raw_response.json())


async def get_user_identity(
    token: str, *, client_factory: GitHubClientFactory = create_github_client
) -> GitHubUserIdentity:
    """Read the execution account from the user token, never from browser input."""
    async with _client(None, client_factory) as client:
        response = await client.rest.users.async_get_authenticated(
            headers=_headers(token)
        )
        identity = _Identity.model_validate(response.raw_response.json())
        return GitHubUserIdentity(
            account_id=identity.id,
            login=identity.login,
            avatar_url=identity.avatar_url,
        )


async def get_app_registration(
    jwt_token: str, *, client_factory: GitHubClientFactory = create_github_client
) -> GitHubUserAppIdentity:
    """Read the App ID and OAuth client ID using authenticated App registration."""
    async with _client(None, client_factory) as client:
        response = await client.rest.apps.async_get_authenticated(
            headers=_headers(jwt_token)
        )
        identity = _AppIdentity.model_validate(response.raw_response.json())
        return GitHubUserAppIdentity(
            app_id=identity.id, slug=identity.slug, client_id=identity.client_id
        )


def _decode_cursor(cursor: str | None) -> _AccessCursor:
    if cursor is None:
        return _AccessCursor(
            installation_page=1, installation_index=0, repository_page=1
        )
    if len(cursor) > 256:
        raise ValueError("Invalid GitHub access continuation cursor.")
    try:
        decoded = base64.b64decode(cursor, altchars=b"-_", validate=True)
        return _AccessCursor.model_validate_json(decoded)
    except ValueError, binascii.Error:
        raise ValueError("Invalid GitHub access continuation cursor.") from None


def _encode_cursor(page: int, index: int, repository_page: int) -> str:
    cursor = _AccessCursor(
        installation_page=page,
        installation_index=index,
        repository_page=repository_page,
    )
    return base64.urlsafe_b64encode(cursor.model_dump_json().encode()).decode()


def _has_next_page(response: httpx.Response) -> bool:
    return "next" in response.links


def _repository_projection(repo: _Repository) -> GitHubUserRepository:
    permissions = repo.permissions
    return GitHubUserRepository(
        repository_id=repo.id,
        owner_login=repo.owner.login,
        name=repo.name,
        full_name=repo.full_name,
        private=repo.private,
        permissions=GitHubUserRepositoryPermissions(
            read=permissions.pull if permissions is not None else None,
            write=permissions.push if permissions is not None else None,
            admin=permissions.admin if permissions is not None else None,
        ),
    )


async def list_user_access(
    token: str,
    *,
    app_id: int,
    cursor: str | None,
    client_factory: GitHubClientFactory = create_github_client,
) -> GitHubUserAccessPage:
    """Traverse selected-App owners/repos with bounded work and a continuation."""
    coordinates = _decode_cursor(cursor)
    async with _client(None, client_factory) as client:
        response = (
            await client.rest.apps.async_list_installations_for_authenticated_user(
                per_page=_PAGE_SIZE,
                page=coordinates.installation_page,
                headers=_headers(token),
            )
        )
        envelope = _Installations.model_validate(response.raw_response.json())
        installations_have_next = _has_next_page(response.raw_response)
        observations: list[GitHubUserInstallation] = []
        repository_requests = 0
        index = coordinates.installation_index
        repository_page = coordinates.repository_page
        while index < len(envelope.installations):
            installation = envelope.installations[index]
            if installation.app_id != app_id:
                index += 1
                repository_page = 1
                continue
            if repository_requests == _REPOSITORY_REQUEST_BUDGET:
                return GitHubUserAccessPage(
                    installations=tuple(observations),
                    next_cursor=_encode_cursor(
                        coordinates.installation_page, index, repository_page
                    ),
                )
            repository_requests += 1
            failure: ProviderFailureReason | None = None
            repositories: tuple[GitHubUserRepository, ...] = ()
            has_more_repos = False
            try:
                async with _client(None, client_factory) as repository_client:
                    apps = repository_client.rest.apps
                    fetch = apps.async_list_installation_repos_for_authenticated_user
                    repos_response = await fetch(
                        installation.id,
                        per_page=_PAGE_SIZE,
                        page=repository_page,
                        headers=_headers(token),
                    )
                    repos = _Repositories.model_validate(
                        repos_response.raw_response.json()
                    )
                    repositories = tuple(
                        _repository_projection(repo) for repo in repos.repositories
                    )
                    has_more_repos = _has_next_page(repos_response.raw_response)
            except GitHubUserProviderError as error:
                if error.reason == "authentication":
                    raise
                failure = error.reason
            observations.append(
                GitHubUserInstallation(
                    installation_id=installation.id,
                    app_id=installation.app_id,
                    account_login=installation.account.login,
                    account_type=installation.account.type,
                    account_avatar_url=installation.account.avatar_url,
                    app_permissions=installation.permissions,
                    repositories=repositories,
                    repositories_complete=not has_more_repos and failure is None,
                    failure_reason=failure,
                )
            )
            if has_more_repos:
                repository_page += 1
            else:
                index += 1
                repository_page = 1
        next_cursor = (
            _encode_cursor(coordinates.installation_page + 1, 0, 1)
            if installations_have_next
            else None
        )
        return GitHubUserAccessPage(
            installations=tuple(observations), next_cursor=next_cursor
        )


async def revoke_user_token(
    *,
    client_id: str,
    client_secret: str,
    token: str,
    client_factory: GitHubClientFactory = create_github_client,
) -> None:
    """Strictly revoke the captured token with observable failures for recovery."""
    async with _client(
        OAuthAppAuthStrategy(client_id, client_secret), client_factory
    ) as client:
        await client.rest.apps.async_delete_token(
            client_id,
            access_token=token,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": _API_VERSION,
            },
        )
