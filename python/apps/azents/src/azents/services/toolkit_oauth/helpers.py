"""Canonical pure projections and external helpers for Toolkit OAuth setup."""

import dataclasses
import json
from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple

import httpx
from pydantic import TypeAdapter, ValidationError

from azents.core.github_installation import GitHubInstallationSnapshot
from azents.core.mcp_credentials import (
    McpSecretsOAuth2,
    McpSecretsOAuth2Dcr,
    McpSecretsOAuth2Token,
)
from azents.core.mcp_discovery import (
    DcrError,
    DiscoveryError,
    OAuthServerMetadata,
    discover_oauth_metadata,
    register_client,
)
from azents.core.oauth2 import (
    OAuthTokenError,
    OAuthTokenResponse,
    exchange_authorization_code,
)
from azents.core.tools import McpToolkitConfig, ToolkitProvider
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnection
from azents.repos.toolkit.data import ToolkitConfiguration
from azents.repos.toolkit_oauth_data import GithubInstallationRecord
from azents.repos.toolkit_operations.owned_data import OAuthConnectionWrite
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)
from azents.services.toolkit.credential_edits import (
    decode_credential_values,
    decode_stored_credential_values,
    merge_credential_edits,
    merge_kubernetes_credentials,
)
from azents.services.toolkit_oauth.data import (
    GitHubInstallationProjection,
    ToolkitConnectionTestInput,
    ToolkitOAuthError,
    ToolkitOAuthFailureReason,
)

_OAuthSecretsUnion = McpSecretsOAuth2 | McpSecretsOAuth2Token | McpSecretsOAuth2Dcr
_oauth_secrets_adapter = TypeAdapter[_OAuthSecretsUnion](_OAuthSecretsUnion)


class OAuthClientCredentials(NamedTuple):
    """Field-named decoded client registration credentials."""

    client_id: str
    client_secret: str | None


@dataclasses.dataclass(frozen=True)
class PreparedMcpAuthorization:
    """Common Provider discovery/registration result, before ownership publication."""

    config: McpToolkitConfig
    connection: OAuthConnectionWrite = dataclasses.field(repr=False)


async def prepare_mcp_authorization(
    toolkit: ToolkitConfiguration,
    existing: MCPOAuthConnection | None,
    *,
    redirect_uri: str,
    proxy_url: str | None,
    registry: Mapping[str, ToolkitProvider[Any]],
) -> PreparedMcpAuthorization:
    """Reuse common discovery, client registration and retained-token behavior."""
    mcp_config = resolve_mcp_config(toolkit.toolkit_type, toolkit.config, registry)
    if mcp_config.auth_type != "oauth2":
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.INVALID_REQUEST,
            "Toolkit does not use OAuth2 authentication.",
        )
    metadata = await discover_required_metadata(mcp_config, proxy_url)
    client_id = existing.client_id if existing is not None else None
    client_secret = existing.client_secret if existing is not None else None
    if client_id is None:
        manual = extract_oauth_client_credentials(toolkit.credentials)
        if manual is not None:
            client_id, client_secret = manual
        elif metadata.registration_endpoint is not None:
            try:
                dcr = await register_client(
                    metadata.registration_endpoint, redirect_uri, proxy_url=proxy_url
                )
            except DcrError as exc:
                raise ToolkitOAuthError(
                    ToolkitOAuthFailureReason.INVALID_REQUEST,
                    f"Dynamic client registration failed: {exc}",
                ) from exc
            client_id = dcr.client_id
            client_secret = dcr.client_secret
        else:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                "OAuth2 client credentials are not configured "
                "and server does not support DCR.",
            )
    return PreparedMcpAuthorization(
        config=mcp_config,
        connection=OAuthConnectionWrite(
            issuer=metadata.issuer,
            resource=mcp_config.server_url,
            server_url=mcp_config.server_url,
            authorization_endpoint=metadata.authorization_endpoint,
            token_endpoint=metadata.token_endpoint,
            registration_endpoint=metadata.registration_endpoint,
            client_id=client_id,
            client_secret=client_secret,
            token_endpoint_auth_method="client_secret_post"
            if client_secret is not None
            else "none",
            scope=" ".join(mcp_config.scopes) if mcp_config.scopes else None,
            access_token=existing.access_token if existing is not None else None,
            refresh_token=existing.refresh_token if existing is not None else None,
            expires_at=existing.expires_at if existing is not None else None,
        ),
    )


def resolve_mcp_config(
    toolkit_type: str,
    config: dict[str, Any],
    registry: Mapping[str, ToolkitProvider[Any]] | None = None,
) -> McpToolkitConfig:
    """Build McpToolkitConfig from toolkit_type."""
    if registry is not None:
        provider = registry.get(toolkit_type)
        if provider is not None:
            typed_config = provider.validate_config(config)
            return provider.to_mcp_config(typed_config)
    return McpToolkitConfig.model_validate(config)


def extract_oauth_client_credentials(
    credentials_json: str | None,
) -> OAuthClientCredentials | None:
    """Extract OAuth client credentials from Toolkit credentials JSON."""
    if credentials_json is None:
        return None
    try:
        secrets = _oauth_secrets_adapter.validate_json(credentials_json)
    except ValidationError:
        return None
    return OAuthClientCredentials(
        client_id=secrets.client_id,
        client_secret=secrets.client_secret,
    )


async def discover_required_metadata(
    mcp_config: McpToolkitConfig,
    proxy_url: str | None,
) -> OAuthServerMetadata:
    """Discover OAuth metadata and apply explicit endpoint overrides."""
    try:
        metadata = await discover_oauth_metadata(
            mcp_config.server_url,
            mcp_config.discovery_url,
            proxy_url=proxy_url,
        )
    except DiscoveryError as exc:
        if mcp_config.auth_url is None or mcp_config.token_url is None:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                f"OAuth metadata discovery failed: {exc}",
            ) from exc
        return OAuthServerMetadata(
            authorization_endpoint=mcp_config.auth_url,
            token_endpoint=mcp_config.token_url,
            registration_endpoint=None,
            scopes_supported=[],
            issuer=None,
        )
    return OAuthServerMetadata(
        authorization_endpoint=mcp_config.auth_url or metadata.authorization_endpoint,
        token_endpoint=mcp_config.token_url or metadata.token_endpoint,
        registration_endpoint=metadata.registration_endpoint,
        scopes_supported=metadata.scopes_supported,
        issuer=metadata.issuer,
    )


async def exchange_and_handle_errors(
    *,
    token_url: str,
    client_id: str,
    client_secret: str | None,
    code: str,
    redirect_uri: str,
    code_verifier: str | None,
    resource: str | None,
    proxy_url: str | None,
    toolkit_id: str,
    user_id: str,
) -> OAuthTokenResponse:
    """Perform OAuth2 code-to-token exchange and classify expected failures."""
    try:
        return await exchange_authorization_code(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            resource=resource,
            proxy_url=proxy_url,
        )
    except httpx.HTTPStatusError as exc:
        if 400 <= exc.response.status_code < 500:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.TOKEN_REJECTED,
                f"Token exchange rejected by provider: HTTP {exc.response.status_code}",
            ) from exc
        raise
    except OAuthTokenError as exc:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.TOKEN_REJECTED,
            f"Token exchange failed: {exc}",
        ) from exc
    except ValidationError as exc:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.TOKEN_REJECTED,
            f"Invalid token response from provider: {exc}",
        ) from exc


def decode_installations(
    installations: Sequence[GitHubInstallationSnapshot],
) -> tuple[GithubInstallationRecord, ...]:
    """Project ordered decoded records with the original persistence avatar fallback."""
    return tuple(
        GithubInstallationRecord(
            installation_id=installation.installation_id,
            account_login=installation.account_login,
            account_type=installation.account_type,
            account_avatar_url=installation.account_avatar_url
            if installation.account_avatar_url is not None
            else "",
        )
        for installation in installations
    )


def project_installations(
    installations: Sequence[GitHubInstallationSnapshot],
) -> tuple[GitHubInstallationProjection, ...]:
    """Project only known Public avatars without changing order or duplicates."""
    return tuple(
        GitHubInstallationProjection(
            id=installation.installation_id,
            account_login=installation.account_login,
            account_type=installation.account_type,
            account_avatar_url=installation.account_avatar_url,
        )
        for installation in installations
        if installation.account_avatar_url is not None
    )


def merge_saved_test_credentials(
    request: ToolkitConnectionTestInput,
    saved_credentials: str | None,
) -> str | None:
    """Merge an eligible saved Toolkit's credentials with its redacted form."""
    if request.toolkit_type == "kubernetes":
        return json.dumps(
            merge_kubernetes_credentials(
                saved_credentials,
                request.credentials,
                request.config,
            )
        )
    saved = decode_stored_credential_values(saved_credentials)
    if request.credentials is not None:
        saved = merge_credential_edits(
            saved, decode_credential_values(request.credentials)
        )
    return json.dumps(saved.to_payload()) if saved.fields else None


@dataclasses.dataclass(frozen=True)
class PreparedPlatformTestCredentials:
    """Normalized test credentials and the exact Platform registration observed."""

    credentials_json: str | None = dataclasses.field(repr=False)
    platform: ResolvedPlatformGitHubApp | None = dataclasses.field(repr=False)


async def prepare_platform_app_test_credentials(
    credentials_json: str | None,
    platform_runtime: PlatformGitHubAppRuntimeService,
) -> PreparedPlatformTestCredentials:
    """Retain the registration needed for current installation-use admission."""
    if credentials_json is None:
        return PreparedPlatformTestCredentials(None, None)
    parsed = decode_credential_values(json.loads(credentials_json))
    if parsed.credential_type != "github_app_platform":
        return PreparedPlatformTestCredentials(credentials_json, None)
    platform = await platform_runtime.resolve()
    if platform.app_id is None:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
            "GitHub Platform App is not configured.",
        )
    return PreparedPlatformTestCredentials(
        json.dumps({**parsed.to_payload(), "app_id": platform.app_id}), platform
    )


async def bind_platform_app_test_credentials(
    credentials_json: str | None,
    platform_runtime: PlatformGitHubAppRuntimeService,
) -> str | None:
    """Preserve common test credential normalization without changing its contract."""
    return (
        await prepare_platform_app_test_credentials(credentials_json, platform_runtime)
    ).credentials_json
