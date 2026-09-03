"""MCP OAuth2 Discovery utilities.

Provides Protected Resource Metadata / Authorization Server Metadata discovery
and Dynamic Client Registration (DCR) according to the MCP spec.

References:
- Protected Resource Metadata: RFC 9728
- Authorization Server Metadata: RFC 8414
- Dynamic Client Registration: RFC 7591
"""

import dataclasses
import logging
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class OAuthServerMetadata:
    """OAuth Authorization Server metadata.

    :param authorization_endpoint: Authorization endpoint
    :param token_endpoint: Token endpoint
    :param registration_endpoint: DCR registration endpoint, or None when unsupported
    :param scopes_supported: Supported OAuth2 scope list
    :param issuer: OAuth issuer, or None when absent
    """

    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    scopes_supported: list[str]
    issuer: str | None = None


@dataclasses.dataclass(frozen=True)
class DcrRegistrationResult:
    """DCR client registration result.

    :param client_id: Issued client ID
    :param client_secret: Issued client secret
    """

    client_id: str
    client_secret: str | None


class _DcrRegistrationPayload(BaseModel):
    """Validated Dynamic Client Registration response payload."""

    client_id: str = Field(min_length=1)
    client_secret: str | None = None


class _ProtectedResourceMetadataPayload(BaseModel):
    """Validated Protected Resource Metadata response payload."""

    authorization_servers: list[str] = Field(min_length=1)


class _AuthorizationServerMetadataPayload(BaseModel):
    """Validated Authorization Server Metadata response payload."""

    authorization_endpoint: str = Field(min_length=1)
    token_endpoint: str = Field(min_length=1)
    registration_endpoint: str | None = None
    scopes_supported: list[str] = Field(default_factory=list)
    issuer: str | None = None


class DiscoveryError(Exception):
    """OAuth metadata discovery failure."""


class DcrError(Exception):
    """Dynamic Client Registration failure."""


async def discover_oauth_metadata(
    server_url: str,
    discovery_url: str | None = None,
    *,
    proxy_url: str | None = None,
) -> OAuthServerMetadata:
    """Automatically discover OAuth metadata from MCP server.

    When discovery_url is absent, perform MCP spec two-step discovery:
    Step 1: GET {server_url}/.well-known/oauth-protected-resource
           → authorization_servers[0] extract
    Step 2: GET {as_url}/.well-known/oauth-authorization-server
           → endpoint information extract

    When discovery_url is provided, query AS metadata directly.

    :param server_url: MCP server URL
    :param discovery_url: OAuth AS discovery URL (override)
    :param proxy_url: Egress proxy URL; direct connection when None
    :return: Authorization Server metadata
    :raises DiscoveryError: On discovery failure
    """
    async with httpx.AsyncClient(
        timeout=15.0, follow_redirects=True, proxy=proxy_url
    ) as client:
        if discovery_url:
            as_issuer = _ensure_absolute_url(discovery_url, server_url)
            return await _fetch_as_metadata(client, as_issuer)

        # Step 1: Protected Resource Metadata → AS issuer extract
        try:
            as_issuer = await _discover_authorization_server(client, server_url)
        except DiscoveryError:
            # When Protected Resource Metadata is not supported
            # fallback by using server_url itself as AS issuer
            logger.info(
                "Protected resource metadata not available, "
                "falling back to server URL as AS issuer",
                extra={"server_url": server_url},
            )
            as_issuer = server_url

        # Step 2: AS Metadata lookup
        return await _fetch_as_metadata(client, as_issuer)


async def register_client(
    registration_endpoint: str,
    redirect_uri: str,
    client_name: str = "Azents",
    *,
    proxy_url: str | None = None,
) -> DcrRegistrationResult:
    """Register OAuth2 client via DCR (RFC 7591).

    :param registration_endpoint: DCR registration endpoint
    :param redirect_uri: Client redirect URI
    :param client_name: Client name
    :param proxy_url: Egress proxy URL; direct connection when None
    :return: Registered client info
    :raises DcrError: On registration failure
    """
    payload = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    }

    try:
        async with httpx.AsyncClient(
            timeout=15.0, follow_redirects=True, proxy=proxy_url
        ) as client:
            response = await client.post(
                registration_endpoint,
                json=payload,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise DcrError(
            f"DCR registration failed: HTTP {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise DcrError(f"DCR registration failed: {exc}") from exc

    try:
        data = _DcrRegistrationPayload.model_validate(response.json())
    except ValidationError as exc:
        raise DcrError("DCR response missing valid client credentials") from exc

    return DcrRegistrationResult(
        client_id=data.client_id,
        client_secret=data.client_secret or None,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_well_known_url(server_url: str, well_known_name: str) -> list[str]:
    """Build well-known URL candidates according to RFC 9728.

    When server URL has a path (e.g. https://host/mcp):
    1. path-aware: {origin}/.well-known/{name}{path}
    2. origin-only: {origin}/.well-known/{name}

    When there is no path:
    1. {origin}/.well-known/{name}

    :param server_url: MCP server URL
    :param well_known_name: Well-known resource name, e.g. "oauth-protected-resource"
    :return: URL candidates to try, in priority order
    """
    parsed = urlparse(server_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")

    if path:
        return [
            f"{origin}/.well-known/{well_known_name}{path}",
            f"{origin}/.well-known/{well_known_name}",
        ]
    return [f"{origin}/.well-known/{well_known_name}"]


def _ensure_absolute_url(url: str, base_url: str) -> str:
    """Validate whether URL is absolute; resolve relative paths against base_url.

    :param url: URL to validate, such as issuer
    :param base_url: Base URL (server_url)
    :return: Absolute URL starting with http(s)://
    :raises DiscoveryError: When URL format is invalid
    """
    if url.startswith("https://") or url.startswith("http://"):
        return url

    # If it starts with slash, resolve as base_url origin + path
    if url.startswith("/"):
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{url}"

    raise DiscoveryError(
        f"Invalid URL '{url}': missing 'http://' or 'https://' protocol"
    )


async def _discover_authorization_server(
    client: httpx.AsyncClient,
    server_url: str,
) -> str:
    """Extract Authorization Server from Protected Resource Metadata.

    Build well-known URL according to RFC 9728:
    - path-aware: {origin}/.well-known/oauth-protected-resource{path}
    - origin-only: {origin}/.well-known/oauth-protected-resource

    :param client: httpx client
    :param server_url: MCP server URL
    :return: Authorization Server issuer URL
    :raises DiscoveryError: Request failure or response format mismatch
    """
    candidates = _build_well_known_url(server_url, "oauth-protected-resource")
    response: httpx.Response | None = None
    last_error: DiscoveryError | None = None

    for url in candidates:
        try:
            resp = await client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            response = resp
            break
        except httpx.HTTPStatusError as exc:
            last_error = DiscoveryError(
                "Protected resource metadata request failed:"
                f" HTTP {exc.response.status_code}"
            )
            last_error.__cause__ = exc
        except httpx.HTTPError as exc:
            last_error = DiscoveryError(
                f"Protected resource metadata request failed: {exc}"
            )
            last_error.__cause__ = exc

    if response is None:
        raise last_error or DiscoveryError("Protected resource metadata request failed")

    try:
        data = _ProtectedResourceMetadataPayload.model_validate(response.json())
    except ValidationError as exc:
        raise DiscoveryError(
            "Protected resource metadata missing valid authorization_servers"
        ) from exc

    return _ensure_absolute_url(data.authorization_servers[0], server_url)


async def _fetch_as_metadata(
    client: httpx.AsyncClient,
    as_issuer: str,
) -> OAuthServerMetadata:
    """Query Authorization Server metadata.

    Build well-known URL according to RFC 8414:
    - path-aware: {origin}/.well-known/oauth-authorization-server{path}
    - origin-only: {origin}/.well-known/oauth-authorization-server

    :param client: httpx client
    :param as_issuer: Authorization Server issuer URL
    :return: Parsed metadata
    :raises DiscoveryError: Request failure or missing required field
    """
    candidates = _build_well_known_url(as_issuer, "oauth-authorization-server")
    response: httpx.Response | None = None
    last_error: DiscoveryError | None = None

    for url in candidates:
        try:
            resp = await client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            response = resp
            break
        except httpx.HTTPStatusError as exc:
            last_error = DiscoveryError(
                f"AS metadata request failed: HTTP {exc.response.status_code}"
            )
            last_error.__cause__ = exc
        except httpx.HTTPError as exc:
            last_error = DiscoveryError(f"AS metadata request failed: {exc}")
            last_error.__cause__ = exc

    if response is None:
        raise last_error or DiscoveryError("AS metadata request failed")

    try:
        data = _AuthorizationServerMetadataPayload.model_validate(response.json())
    except ValidationError as exc:
        raise DiscoveryError("AS metadata has invalid response shape") from exc

    return OAuthServerMetadata(
        authorization_endpoint=data.authorization_endpoint,
        token_endpoint=data.token_endpoint,
        registration_endpoint=data.registration_endpoint,
        scopes_supported=data.scopes_supported,
        issuer=data.issuer,
    )
