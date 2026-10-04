"""GitHub App authentication through supported public GitHubKit operations."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
import jwt
from githubkit import (
    BaseAuthStrategy,
    GitHub,
    OAuthAppAuthStrategy,
    OAuthWebAuthStrategy,
    UnauthAuthStrategy,
)
from githubkit.exception import AuthExpiredError, RequestError
from pydantic import BaseModel, ConfigDict, StrictStr

from azents.core.github_installation import (
    GitHubInstallationSnapshot,
    decode_github_installations,
)

logger = logging.getLogger(__name__)

GitHubClientFactory = Callable[[BaseAuthStrategy | None], GitHub[BaseAuthStrategy]]
_API_VERSION = "2022-11-28"


class _AppMetadata(BaseModel):
    """Ingress scalar contract with compatible external GitHub extension fields."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    slug: StrictStr


class _InstallationToken(BaseModel):
    """Ingress token contract; expiration and provider extension fields are opaque."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    token: StrictStr


class _OAuthFailure(BaseModel):
    """Known provider OAuth rejection fields at ingress."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    error: str = "unknown_error"
    error_description: str | None = None


class _UserInstallationEnvelope(BaseModel):
    """Validate the outer response object before its legacy-compatible list decoder."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    installations: object = None


def create_github_client(auth: BaseAuthStrategy | None) -> GitHub[BaseAuthStrategy]:
    """Construct an operation-owned SDK client without retries or response caching."""
    return GitHub[BaseAuthStrategy](
        auth=auth if auth is not None else UnauthAuthStrategy(),
        timeout=5.0,
        follow_redirects=False,
        auto_retry=False,
        http_cache=False,
    )


@asynccontextmanager
async def _sdk_error_contract() -> AsyncIterator[None]:
    """Preserve underlying failures without treating programming defects as cleanup."""
    try:
        yield
    except asyncio.CancelledError:
        raise
    except RequestError as error:
        raise error.exc from error


@asynccontextmanager
async def _github_client(
    auth: BaseAuthStrategy | None,
    client_factory: GitHubClientFactory,
) -> AsyncIterator[GitHub[BaseAuthStrategy]]:
    """Own the ordinary REST operation's SDK lifetime."""
    async with _sdk_error_contract():
        async with client_factory(auth) as client:
            yield client


def _bearer_headers(token: str) -> dict[str, str]:
    """Preserve the established bearer and version contract through SDK headers."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _API_VERSION,
    }


def create_github_app_jwt(app_id: str, private_key: str) -> str:
    """Create RS256 JWT with the existing 9-minute expiry and 60-second backdate."""
    normalized_key = private_key.replace("\\n", "\n")
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": app_id}
    return jwt.encode(payload, normalized_key, algorithm="RS256")


async def get_app_slug(
    jwt_token: str,
    *,
    client_factory: GitHubClientFactory = create_github_client,
) -> str:
    """Read the authenticated App slug through the public SDK operation."""
    async with _github_client(None, client_factory) as client:
        response = await client.rest.apps.async_get_authenticated(
            headers=_bearer_headers(jwt_token)
        )
        return _AppMetadata.model_validate(response.raw_response.json()).slug


async def exchange_oauth_code(
    client_id: str,
    client_secret: str,
    code: str,
    *,
    client_factory: GitHubClientFactory = create_github_client,
) -> str:
    """Exchange an authorization code through the SDK's public OAuth Web strategy."""
    strategy = OAuthWebAuthStrategy(client_id, client_secret, code)
    try:
        async with _sdk_error_contract():
            # The public OAuth strategy owns its client's context and close.
            auth = await strategy.async_exchange_token(client_factory(None))
    except AuthExpiredError as error:
        failure = _OAuthFailure.model_validate(
            error.args[1] if len(error.args) > 1 else {}
        )
        message = f"OAuth token exchange failed: {failure.error}"
        if failure.error_description:
            message += f" - {failure.error_description}"
        raise ValueError(message) from None
    if not isinstance(auth.token, str) or not auth.token:
        raise ValueError("OAuth token exchange failed: token is missing")
    return auth.token


async def list_user_installations(
    user_token: str,
    *,
    client_factory: GitHubClientFactory = create_github_client,
) -> tuple[GitHubInstallationSnapshot, ...]:
    """Decode the original first 100 user-visible installations at SDK ingress."""
    async with _github_client(None, client_factory) as client:
        response = (
            await client.rest.apps.async_list_installations_for_authenticated_user(
                per_page=100, headers=_bearer_headers(user_token)
            )
        )
        # This is the sole operation-specific ingress decoder. Generated SDK
        # model coercion would change legacy boolean-ID and malformed-skip behavior.
        payload = _UserInstallationEnvelope.model_validate(response.raw_response.json())
        return decode_github_installations(payload.installations)


async def list_installations(
    jwt_token: str,
    *,
    client_factory: GitHubClientFactory = create_github_client,
) -> tuple[GitHubInstallationSnapshot, ...]:
    """Decode the original first 100 App installations through the public SDK."""
    async with _github_client(None, client_factory) as client:
        response = await client.rest.apps.async_list_installations(
            per_page=100, headers=_bearer_headers(jwt_token)
        )
        return decode_github_installations(response.raw_response.json())


async def revoke_oauth_token(
    client_id: str,
    client_secret: str,
    token: str,
    *,
    client_factory: GitHubClientFactory = create_github_client,
) -> None:
    """Revoke one temporary token with SDK Basic auth and best-effort HTTP cleanup."""
    try:
        async with _github_client(
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
    except asyncio.CancelledError:
        raise
    except httpx.HTTPError:
        logger.warning("Failed to revoke GitHub OAuth token", exc_info=True)


async def get_installation(
    jwt_token: str,
    installation_id: str,
    *,
    client_factory: GitHubClientFactory = create_github_client,
) -> GitHubInstallationSnapshot:
    """Return one typed App installation instead of unvalidated provider JSON."""
    async with _github_client(None, client_factory) as client:
        response = await client.rest.apps.async_get_installation(
            int(installation_id), headers=_bearer_headers(jwt_token)
        )
        records = decode_github_installations([response.raw_response.json()])
        if not records:
            raise ValueError("GitHub installation response has invalid identity fields")
        return records[0]


async def exchange_installation_token(
    jwt_token: str,
    installation_id: str,
    *,
    client_factory: GitHubClientFactory = create_github_client,
) -> str:
    """Issue an installation token through the supported App access-token operation."""
    async with _github_client(None, client_factory) as client:
        response = await client.rest.apps.async_create_installation_access_token(
            int(installation_id), headers=_bearer_headers(jwt_token)
        )
        return _InstallationToken.model_validate(response.raw_response.json()).token
