"""Canonical pure projections and external helpers for Toolkit OAuth setup."""

import json
import logging
from collections.abc import Mapping
from typing import Any, NamedTuple

import httpx
from pydantic import TypeAdapter, ValidationError

from azents.core.mcp_credentials import (
    McpSecretsOAuth2,
    McpSecretsOAuth2Dcr,
    McpSecretsOAuth2Token,
)
from azents.core.mcp_discovery import (
    DiscoveryError,
    OAuthServerMetadata,
    discover_oauth_metadata,
)
from azents.core.oauth2 import (
    OAuthTokenError,
    OAuthTokenResponse,
    exchange_authorization_code,
)
from azents.core.tools import McpToolkitConfig, ToolkitProvider
from azents.repos.toolkit_oauth_data import GithubInstallationRecord
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.toolkit.credential_edits import (
    merge_kubernetes_credentials,
    merge_redacted_credential_values,
)
from azents.services.toolkit_oauth.data import (
    GitHubInstallationProjection,
    ToolkitConnectionTestInput,
    ToolkitOAuthError,
    ToolkitOAuthFailureReason,
)

logger = logging.getLogger(__name__)
_OAuthSecretsUnion = McpSecretsOAuth2 | McpSecretsOAuth2Token | McpSecretsOAuth2Dcr
_oauth_secrets_adapter = TypeAdapter[_OAuthSecretsUnion](_OAuthSecretsUnion)
_credentials_adapter = TypeAdapter(dict[str, object])


class OAuthClientCredentials(NamedTuple):
    """Field-named decoded client registration credentials."""

    client_id: str
    client_secret: str | None


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
        logger.warning(
            "Invalid token response from provider",
            extra={"toolkit_id": toolkit_id, "user_id": user_id},
            exc_info=True,
        )
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.TOKEN_REJECTED,
            f"Invalid token response from provider: {exc}",
        ) from exc


def decode_installations(
    installations: list[dict[str, object]],
) -> tuple[GithubInstallationRecord, ...]:
    """Decode ordered persistence rows with the original skip/avatar semantics."""
    records: list[GithubInstallationRecord] = []
    for installation in installations:
        installation_id = installation.get("id")
        account = installation.get("account")
        if not isinstance(installation_id, int) or not isinstance(account, dict):
            continue
        login = account.get("login")
        account_type = account.get("type")
        avatar_url = account.get("avatar_url", "")
        if not isinstance(login, str) or not isinstance(account_type, str):
            continue
        records.append(
            GithubInstallationRecord(
                installation_id=installation_id,
                account_login=login,
                account_type=account_type,
                account_avatar_url=avatar_url if isinstance(avatar_url, str) else "",
            )
        )
    return tuple(records)


def project_installations(
    installations: list[dict[str, object]],
) -> tuple[GitHubInstallationProjection, ...]:
    """Decode the stricter Public avatar projection without deduplicating rows."""
    items: list[GitHubInstallationProjection] = []
    for installation in installations:
        account = installation.get("account")
        if not isinstance(account, dict):
            continue
        installation_id = installation.get("id")
        login = account.get("login")
        account_type = account.get("type")
        avatar_url = account.get("avatar_url")
        if (
            isinstance(installation_id, int)
            and isinstance(login, str)
            and isinstance(account_type, str)
            and isinstance(avatar_url, str)
        ):
            items.append(
                GitHubInstallationProjection(
                    id=installation_id,
                    account_login=login,
                    account_type=account_type,
                    account_avatar_url=avatar_url,
                )
            )
    return tuple(items)


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
    saved: dict[str, object] = {}
    if saved_credentials is not None:
        try:
            saved = _credentials_adapter.validate_json(saved_credentials)
        except ValidationError:
            pass
    if request.credentials is not None:
        saved = merge_redacted_credential_values(saved, request.credentials)
    return json.dumps(saved) if saved else None


async def bind_platform_app_test_credentials(
    credentials_json: str | None,
    platform_runtime: PlatformGitHubAppRuntimeService,
) -> str | None:
    """Bind unsaved Platform GitHub credentials to the server App identity."""
    if credentials_json is None:
        return None
    parsed: object = json.loads(credentials_json)
    if not isinstance(parsed, dict) or parsed.get("type") != "github_app_platform":
        return credentials_json
    platform = await platform_runtime.resolve()
    if platform.app_id is None:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
            "GitHub Platform App is not configured.",
        )
    return json.dumps({**parsed, "app_id": platform.app_id})
