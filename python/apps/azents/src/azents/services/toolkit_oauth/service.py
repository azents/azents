"""Sequence completed Toolkit OAuth operations and external provider effects."""

import dataclasses
import json
from typing import Annotated, Any, assert_never

import httpx
from azcommon.result import Result
from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.github_auth import (
    exchange_oauth_code,
    list_user_installations,
    revoke_oauth_token,
)
from azents.core.mcp_discovery import DcrError, register_client
from azents.core.oauth2 import (
    build_authorization_url,
    create_toolkit_oauth_state,
    generate_pkce_pair,
    verify_platform_oauth_state,
    verify_toolkit_oauth_state,
)
from azents.core.tools import TestConnectionResult, ToolkitProvider
from azents.engine.tools.deps import get_toolkit_registry
from azents.repos.toolkit_oauth_data import (
    ToolkitOAuthDenialReason,
    ToolkitOAuthDenied,
    ToolkitOAuthRequester,
)
from azents.repos.toolkit_oauth_operations import ToolkitOAuthOperationRepository
from azents.repos.toolkit_operations.owned_data import OAuthConnectionWrite
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.toolkit_oauth import helpers
from azents.services.toolkit_oauth.data import (
    GitHubInstallationProjection,
    ToolkitConnectionTestInput,
    ToolkitOAuthError,
    ToolkitOAuthFailureReason,
)


def _require_authority(result: Result[None, ToolkitOAuthDenied]) -> None:
    """Project only expected detached repository denials to domain failures."""
    if result.success:
        return
    denial = result.error
    match denial.reason:
        case ToolkitOAuthDenialReason.INACTIVE_SUBJECT:
            reason = ToolkitOAuthFailureReason.INACTIVE_SUBJECT
            detail = "Not authenticated"
        case ToolkitOAuthDenialReason.WORKSPACE_NOT_FOUND:
            reason = ToolkitOAuthFailureReason.WORKSPACE_NOT_FOUND
            detail = "Workspace not found."
        case ToolkitOAuthDenialReason.MEMBERSHIP_REQUIRED:
            reason = ToolkitOAuthFailureReason.MEMBERSHIP_REQUIRED
            detail = "Not a member of this workspace."
        case ToolkitOAuthDenialReason.WRITE_PERMISSION_REQUIRED:
            reason = ToolkitOAuthFailureReason.WRITE_PERMISSION_REQUIRED
            detail = "Toolkit write permission required."
        case ToolkitOAuthDenialReason.TOOLKIT_NOT_FOUND:
            reason = ToolkitOAuthFailureReason.TOOLKIT_NOT_FOUND
            detail = "Toolkit config not found."
        case _:
            assert_never(denial.reason)
    raise ToolkitOAuthError(reason, detail)


@dataclasses.dataclass(frozen=True)
class ToolkitOAuthService:
    """Orchestrate shared setup without receiving database lifetime handles."""

    repository: Annotated[
        ToolkitOAuthOperationRepository, Depends(ToolkitOAuthOperationRepository)
    ]
    config: Annotated[Config, Depends(get_config)]
    registry: Annotated[dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)]
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()]

    async def platform_installations(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_id: str,
        code: str,
        state: str,
    ) -> tuple[GitHubInstallationProjection, ...]:
        """Sync one User/App snapshot and revoke the token only after success."""
        oauth_state = verify_platform_oauth_state(
            state, self.config.credential_encryption.key
        )
        if oauth_state is None:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                "Invalid state parameter.",
            )
        platform = await self.platform_runtime.resolve()
        if oauth_state.effective_generation != platform.effective_generation:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.PLATFORM_SETTINGS_CHANGED,
                "Platform GitHub App settings changed. Restart OAuth.",
            )
        if (
            platform.app_id is None
            or platform.client_id is None
            or platform.client_secret is None
        ):
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
                "GitHub Platform App OAuth is not configured.",
            )
        try:
            user_token = await exchange_oauth_code(
                platform.client_id, platform.client_secret, code
            )
        except ValueError as exc:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST, str(exc)
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"GitHub OAuth token exchange failed: HTTP {exc.response.status_code}"
            ) from exc
        try:
            raw_installations = await list_user_installations(user_token)
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Failed to fetch user installations: HTTP {exc.response.status_code}"
            ) from exc
        records = helpers.decode_installations(raw_installations)
        result = await self.repository.sync_installations(
            requester=ToolkitOAuthRequester(
                user_id=user_id,
                session_id=session_id,
                workspace_id=workspace_id,
            ),
            platform_app_id=platform.app_id,
            installations=records,
        )
        _require_authority(result)
        await revoke_oauth_token(platform.client_id, platform.client_secret, user_token)
        return helpers.project_installations(raw_installations)

    async def connect(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_id: str,
        handle: str,
        toolkit_id: str,
    ) -> str:
        """Prepare shared OAuth metadata while retaining preflight token fields."""
        context = await self.repository.read_shared_context(toolkit_id=toolkit_id)
        toolkit = context.toolkit
        existing = context.connection
        if toolkit is None or toolkit.workspace_id != workspace_id:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
                "Toolkit config not found.",
            )
        mcp_config = helpers.resolve_mcp_config(
            toolkit.toolkit_type, toolkit.config, self.registry
        )
        if mcp_config.auth_type != "oauth2":
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                "Toolkit does not use OAuth2 authentication.",
            )
        metadata = await helpers.discover_required_metadata(
            mcp_config, self.config.mcp_proxy_url
        )
        redirect_uri = (
            f"{self.config.web_url}/oauth/mcp/callback"
            f"?handle={handle}&toolkit_config_id={toolkit_id}"
            if self.config.web_url
            else ""
        )
        client_id = existing.client_id if existing is not None else None
        client_secret = existing.client_secret if existing is not None else None
        if client_id is None:
            manual = helpers.extract_oauth_client_credentials(toolkit.credentials)
            if manual is not None:
                client_id, client_secret = manual
            elif metadata.registration_endpoint is not None:
                try:
                    dcr = await register_client(
                        metadata.registration_endpoint,
                        redirect_uri,
                        proxy_url=self.config.mcp_proxy_url,
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
        pkce = generate_pkce_pair()
        oauth_state = create_toolkit_oauth_state(
            toolkit_id=toolkit_id,
            workspace_id=workspace_id,
            user_id=user_id,
            redirect_uri=redirect_uri,
            code_verifier=pkce.code_verifier,
            secret_key=self.config.credential_encryption.key,
        )
        result = await self.repository.store_shared_connection(
            requester=ToolkitOAuthRequester(
                user_id=user_id,
                session_id=session_id,
                workspace_id=workspace_id,
            ),
            toolkit_id=toolkit_id,
            connection=OAuthConnectionWrite(
                issuer=metadata.issuer,
                resource=mcp_config.server_url,
                server_url=mcp_config.server_url,
                authorization_endpoint=metadata.authorization_endpoint,
                token_endpoint=metadata.token_endpoint,
                registration_endpoint=metadata.registration_endpoint,
                client_id=client_id,
                client_secret=client_secret,
                token_endpoint_auth_method=(
                    "client_secret_post" if client_secret is not None else "none"
                ),
                scope=" ".join(mcp_config.scopes) if mcp_config.scopes else None,
                access_token=existing.access_token if existing is not None else None,
                refresh_token=existing.refresh_token if existing is not None else None,
                expires_at=existing.expires_at if existing is not None else None,
            ),
        )
        _require_authority(result)
        return build_authorization_url(
            auth_url=metadata.authorization_endpoint,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=mcp_config.scopes,
            state=oauth_state,
            code_challenge=pkce.code_challenge,
            resource=mcp_config.server_url,
        )

    async def exchange(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_id: str,
        toolkit_id: str,
        code: str,
        state: str,
    ) -> None:
        """Exchange with captured fields and repeat existing authority at store."""
        verified = verify_toolkit_oauth_state(
            state, self.config.credential_encryption.key
        )
        if verified is None:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                "Invalid state parameter.",
            )
        if verified.toolkit_id != toolkit_id or verified.workspace_id != workspace_id:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                "OAuth state does not match toolkit.",
            )
        context = await self.repository.read_shared_context(toolkit_id=toolkit_id)
        toolkit = context.toolkit
        connection = context.connection
        if toolkit is None or toolkit.workspace_id != workspace_id:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
                "Toolkit config not found.",
            )
        if connection is None:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
                "OAuth connection not found. Start connect again.",
            )
        mcp_config = helpers.resolve_mcp_config(
            toolkit.toolkit_type, toolkit.config, self.registry
        )
        if mcp_config.auth_type != "oauth2":
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                "Toolkit does not use OAuth2 authentication.",
            )
        token_response = await helpers.exchange_and_handle_errors(
            token_url=connection.token_endpoint,
            client_id=connection.client_id,
            client_secret=connection.client_secret,
            code=code,
            redirect_uri=verified.redirect_uri,
            code_verifier=verified.code_verifier,
            resource=connection.resource or mcp_config.server_url,
            proxy_url=self.config.mcp_proxy_url,
            toolkit_id=toolkit_id,
            user_id=user_id,
        )
        result = await self.repository.store_shared_connection(
            requester=ToolkitOAuthRequester(
                user_id=user_id,
                session_id=session_id,
                workspace_id=workspace_id,
            ),
            toolkit_id=toolkit_id,
            connection=OAuthConnectionWrite(
                issuer=connection.issuer,
                resource=connection.resource,
                server_url=connection.server_url,
                authorization_endpoint=connection.authorization_endpoint,
                token_endpoint=connection.token_endpoint,
                registration_endpoint=connection.registration_endpoint,
                client_id=connection.client_id,
                client_secret=connection.client_secret,
                token_endpoint_auth_method=connection.token_endpoint_auth_method,
                scope=connection.scope,
                access_token=token_response.access_token,
                refresh_token=token_response.refresh_token,
                expires_at=token_response.expires_at,
            ),
        )
        _require_authority(result)

    async def disconnect(self, *, workspace_id: str, toolkit_id: str) -> None:
        """Delete the local shared connection without a provider revocation."""
        _require_authority(
            await self.repository.delete_shared_connection(
                workspace_id=workspace_id, toolkit_id=toolkit_id
            )
        )

    async def test_saved(
        self, *, workspace_id: str, toolkit_id: str
    ) -> TestConnectionResult:
        """Test an eligible saved snapshot after its read operation completes."""
        toolkit = await self.repository.read_shared_toolkit(
            workspace_id=workspace_id, toolkit_id=toolkit_id
        )
        if toolkit is None:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
                "Toolkit config not found.",
            )
        provider = self.registry.get(toolkit.toolkit_type)
        if provider is None:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                f"Unknown toolkit type: {toolkit.toolkit_type}",
            )
        validated_config = provider.validate_config(toolkit.config)
        return await provider.test_connection(
            validated_config,
            toolkit.credentials,
            proxy_url=self.config.mcp_proxy_url,
        )

    async def test_unsaved(
        self, *, workspace_id: str, request: ToolkitConnectionTestInput
    ) -> TestConnectionResult:
        """Merge an optional eligible snapshot without creating a resource."""
        provider = self.registry.get(request.toolkit_type)
        if provider is None:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                f"Unknown toolkit type: {request.toolkit_type}",
            )
        validated_config = provider.validate_config(request.config)
        toolkit = await self.repository.read_optional_shared_toolkit(
            workspace_id=workspace_id,
            toolkit_id=request.toolkit_config_id,
        )
        if toolkit is not None:
            credentials_json = helpers.merge_saved_test_credentials(
                request, toolkit.credentials
            )
        else:
            credentials_json = (
                json.dumps(request.credentials)
                if request.credentials is not None
                else None
            )
        credentials_json = await helpers.bind_platform_app_test_credentials(
            credentials_json, self.platform_runtime
        )
        return await provider.test_connection(
            validated_config, credentials_json, proxy_url=self.config.mcp_proxy_url
        )
