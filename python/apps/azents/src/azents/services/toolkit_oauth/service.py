"""Sequence completed Toolkit OAuth operations and external provider effects."""

import dataclasses
import json
from typing import Annotated, Any, assert_never

import httpx
from azcommon.result import Result
from fastapi import Depends

from azents.core.auth.deps import WorkspaceMember
from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import MCPOAuthConnectionStatus
from azents.core.github_auth import (
    GitHubClientFactory,
    create_github_app_jwt,
    create_github_client,
    exchange_oauth_code,
    get_app_slug,
    list_user_installations,
    revoke_oauth_token,
)
from azents.core.github_user_testenv import github_user_testenv_client_factory
from azents.core.mcp_discovery import DcrError, register_client
from azents.core.oauth2 import (
    build_authorization_url,
    create_agent_github_platform_oauth_state,
    create_agent_toolkit_oauth_state,
    create_platform_oauth_state,
    create_toolkit_oauth_state,
    generate_pkce_pair,
    verify_agent_github_platform_oauth_state,
    verify_agent_toolkit_oauth_state,
    verify_platform_oauth_state,
    verify_toolkit_oauth_state,
)
from azents.core.toolkit_errors import NotFound
from azents.core.tools import TestConnectionResult, ToolkitProvider
from azents.engine.tools.deps import get_toolkit_registry
from azents.repos.toolkit_oauth_data import (
    GithubInstallationRecord,
    ToolkitOAuthDenialReason,
    ToolkitOAuthDenied,
    ToolkitOAuthRequester,
)
from azents.repos.toolkit_oauth_operations import ToolkitOAuthOperationRepository
from azents.repos.toolkit_operations.owned_data import OAuthConnectionWrite
from azents.services.agent.data import NotAdmin
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import (
    AgentNotBelongToWorkspace,
    AgentToolkitOAuthConnectionInput,
    AgentToolkitOAuthContext,
    ToolkitOutput,
)
from azents.services.toolkit_oauth import helpers
from azents.services.toolkit_oauth.data import (
    GitHubInstallationProjection,
    ToolkitConnectionTestInput,
    ToolkitOAuthError,
    ToolkitOAuthFailureReason,
)


@dataclasses.dataclass(frozen=True)
class PlatformInstallationReceipt:
    """Transient SDK receipt, retained only until the ordinary sync/cleanup sequence."""

    token: str = dataclasses.field(repr=False)
    client_factory: GitHubClientFactory = dataclasses.field(repr=False)
    records: tuple[GithubInstallationRecord, ...]
    installations: tuple[GitHubInstallationProjection, ...]


async def exchange_platform_installations(
    config: Config,
    platform: ResolvedPlatformGitHubApp,
    code: str,
) -> PlatformInstallationReceipt:
    """Reuse the established SDK exchange/list behavior for every management owner."""
    if (
        platform.app_id is None
        or platform.client_id is None
        or platform.client_secret is None
    ):
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
            "GitHub Platform App OAuth is not configured.",
        )
    base_url = config.testenv_github_platform_validation_base_url
    client_factory = (
        github_user_testenv_client_factory(base_url)
        if config.testenv_api_enabled and base_url is not None
        else create_github_client
    )
    try:
        token = await exchange_oauth_code(
            platform.client_id,
            platform.client_secret,
            code,
            client_factory=client_factory,
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
        raw = await list_user_installations(token, client_factory=client_factory)
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Failed to fetch user installations: HTTP {exc.response.status_code}"
        ) from exc
    return PlatformInstallationReceipt(
        token=token,
        client_factory=client_factory,
        records=helpers.decode_installations(raw),
        installations=helpers.project_installations(raw),
    )


async def revoke_platform_installation_receipt(
    platform: ResolvedPlatformGitHubApp,
    receipt: PlatformInstallationReceipt,
) -> None:
    """Perform the existing token revocation only after successful local sync."""
    if platform.client_id is None or platform.client_secret is None:
        raise RuntimeError("Admitted Platform registration is incomplete")
    await revoke_oauth_token(
        platform.client_id,
        platform.client_secret,
        receipt.token,
        client_factory=receipt.client_factory,
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
        receipt = await exchange_platform_installations(self.config, platform, code)
        if platform.app_id is None:
            raise RuntimeError("Admitted Platform registration is incomplete")
        result = await self.repository.sync_installations(
            requester=ToolkitOAuthRequester(
                user_id=user_id,
                session_id=session_id,
                workspace_id=workspace_id,
            ),
            platform_app_id=platform.app_id,
            installations=receipt.records,
        )
        _require_authority(result)
        await revoke_platform_installation_receipt(platform, receipt)
        return receipt.installations

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
        redirect_uri = (
            f"{self.config.web_url}/oauth/mcp/callback"
            f"?handle={handle}&toolkit_config_id={toolkit_id}"
            if self.config.web_url
            else ""
        )
        prepared = await helpers.prepare_mcp_authorization(
            toolkit,
            existing,
            redirect_uri=redirect_uri,
            proxy_url=self.config.mcp_proxy_url,
            registry=self.registry,
        )
        mcp_config = prepared.config
        connection = prepared.connection
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
            connection=connection,
        )
        _require_authority(result)
        return build_authorization_url(
            auth_url=connection.authorization_endpoint,
            client_id=connection.client_id,
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


_AGENT_TOOLKIT_CALLBACK_TARGET = "agent_toolkits"
_AGENT_GITHUB_CALLBACK_TARGET = "agent_github_installations"


async def platform_install_url(
    platform_runtime: PlatformGitHubAppRuntimeService,
) -> str:
    """Return the GitHub Platform App installation URL.

    Creates a JWT with Platform App credentials configured on the server,
    calls the GitHub API to fetch the App slug, then builds the installation URL.
    Requires Toolkit write permission.
    """
    platform = await platform_runtime.resolve()
    if platform.app_id is None or platform.private_key is None:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
            "GitHub Platform App is not configured.",
        )
    try:
        jwt_token = create_github_app_jwt(platform.app_id, platform.private_key)
        slug = await get_app_slug(jwt_token)
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Failed to fetch GitHub App info: HTTP {exc.response.status_code}"
        ) from exc
    install_url = f"https://github.com/apps/{slug}/installations/new"
    return install_url


async def platform_oauth_url(
    config: Config, platform_runtime: PlatformGitHubAppRuntimeService
) -> str:
    """Return the GitHub Platform App OAuth authorization URL.

    Starts an OAuth flow so the user can log in to GitHub and list their own
    installations. Requires Toolkit write permission.
    """
    platform = await platform_runtime.resolve()
    if platform.client_id is None:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
            "GitHub Platform App OAuth is not configured.",
        )
    redirect_uri = f"{config.web_url}/oauth/github/callback" if config.web_url else ""
    state = create_platform_oauth_state(
        config.credential_encryption.key,
        effective_generation=platform.effective_generation,
    )
    oauth_url = f"https://github.com/login/oauth/authorize?client_id={platform.client_id}&redirect_uri={redirect_uri}&state={state}"
    return oauth_url


async def agent_platform_install_url(
    member: WorkspaceMember,
    service: ToolkitService,
    platform_runtime: PlatformGitHubAppRuntimeService,
    *,
    agent_id: str,
) -> str:
    """Return the Platform GitHub App install URL for Agent Toolkit setup."""
    await authorize_agent_management(service, member, agent_id=agent_id)
    platform = await platform_runtime.resolve()
    if platform.app_id is None or platform.private_key is None:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
            "GitHub Platform App is not configured.",
        )
    try:
        jwt_token = create_github_app_jwt(platform.app_id, platform.private_key)
        slug = await get_app_slug(jwt_token)
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Failed to fetch GitHub App info: HTTP {exc.response.status_code}"
        ) from exc
    return f"https://github.com/apps/{slug}/installations/new"


async def agent_platform_oauth_url(
    member: WorkspaceMember,
    service: ToolkitService,
    config: Config,
    platform_runtime: PlatformGitHubAppRuntimeService,
    *,
    handle: str,
    agent_id: str,
) -> str:
    """Return the Platform GitHub user OAuth URL for Agent Toolkit setup."""
    await authorize_agent_management(service, member, agent_id=agent_id)
    platform = await platform_runtime.resolve()
    if platform.client_id is None:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
            "GitHub Platform App OAuth is not configured.",
        )
    redirect_uri = f"{config.web_url}/oauth/github/callback" if config.web_url else ""
    state = create_agent_github_platform_oauth_state(
        config.credential_encryption.key,
        effective_generation=platform.effective_generation,
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        user_id=member.user_id,
        redirect_uri=redirect_uri,
        callback_target=_AGENT_GITHUB_CALLBACK_TARGET,
    )
    return f"https://github.com/login/oauth/authorize?client_id={platform.client_id}&redirect_uri={redirect_uri}&state={state}"


async def agent_platform_installations(
    member: WorkspaceMember,
    service: ToolkitService,
    config: Config,
    platform_runtime: PlatformGitHubAppRuntimeService,
    code: str,
    *,
    agent_id: str,
    state: str,
) -> tuple[GitHubInstallationProjection, ...]:
    """Return GitHub installations for authorized Agent Toolkit setup."""
    await authorize_agent_management(service, member, agent_id=agent_id)
    oauth_state = verify_agent_github_platform_oauth_state(
        state, config.credential_encryption.key
    )
    expected_redirect_uri = (
        f"{config.web_url}/oauth/github/callback" if config.web_url else ""
    )
    if (
        oauth_state is None
        or oauth_state.workspace_id != member.workspace_id
        or oauth_state.agent_id != agent_id
        or (oauth_state.user_id != member.user_id)
        or (oauth_state.redirect_uri != expected_redirect_uri)
        or (oauth_state.callback_target != _AGENT_GITHUB_CALLBACK_TARGET)
    ):
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.INVALID_REQUEST,
            "OAuth state does not match Agent GitHub setup.",
        )
    platform = await platform_runtime.resolve()
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
    base_url = config.testenv_github_platform_validation_base_url
    client_factory = (
        github_user_testenv_client_factory(base_url)
        if config.testenv_api_enabled and base_url is not None
        else create_github_client
    )
    try:
        user_token = await exchange_oauth_code(
            platform.client_id,
            platform.client_secret,
            code,
            client_factory=client_factory,
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
        try:
            raw_installations = await list_user_installations(
                user_token, client_factory=client_factory
            )
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Failed to fetch user installations: HTTP {exc.response.status_code}"
            ) from exc
        sync_result = await service.sync_agent_github_installations(
            agent_id,
            workspace_id=member.workspace_id,
            workspace_user_id=member.workspace_user_id,
            user_id=member.user_id,
            role=member.role,
            platform_app_id=platform.app_id,
            installations=raw_installations,
        )
        _require_agent_management(sync_result)
    finally:
        await revoke_oauth_token(
            platform.client_id,
            platform.client_secret,
            user_token,
            client_factory=client_factory,
        )
    items: list[GitHubInstallationProjection] = []
    for installation in raw_installations:
        if installation.account_avatar_url is None:
            continue
        items.append(
            GitHubInstallationProjection(
                id=installation.installation_id,
                account_login=installation.account_login,
                account_type=installation.account_type,
                account_avatar_url=installation.account_avatar_url,
            )
        )
    return tuple(items)


async def connect_agent(
    member: WorkspaceMember,
    service: ToolkitService,
    config: Config,
    registry: dict[str, ToolkitProvider[Any]],
    *,
    handle: str,
    agent_id: str,
    toolkit_config_id: str,
) -> str:
    """Create an OAuth authorization URL for an Agent-owned Toolkit."""
    context = await _get_agent_oauth_context(
        service, member, agent_id=agent_id, toolkit_config_id=toolkit_config_id
    )
    toolkit = context.toolkit
    existing = context.connection
    mcp_config = helpers.resolve_mcp_config(
        toolkit.toolkit_type, toolkit.config, registry
    )
    if mcp_config.auth_type != "oauth2":
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.INVALID_REQUEST,
            "Toolkit does not use OAuth2 authentication.",
        )
    metadata = await helpers.discover_required_metadata(
        mcp_config, config.mcp_proxy_url
    )
    redirect_uri = (
        f"{config.web_url}/oauth/mcp/callback?handle={handle}&agent_id={agent_id}&toolkit_config_id={toolkit_config_id}"
        if config.web_url
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
                    proxy_url=config.mcp_proxy_url,
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
    oauth_state = create_agent_toolkit_oauth_state(
        toolkit_id=toolkit_config_id,
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        user_id=member.user_id,
        redirect_uri=redirect_uri,
        code_verifier=pkce.code_verifier,
        callback_target=_AGENT_TOOLKIT_CALLBACK_TARGET,
        secret_key=config.credential_encryption.key,
    )
    scope = " ".join(mcp_config.scopes) if mcp_config.scopes else None
    store_result = await service.store_agent_oauth_connection(
        agent_id,
        toolkit_config_id,
        AgentToolkitOAuthConnectionInput(
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
            scope=scope,
            access_token=existing.access_token if existing is not None else None,
            refresh_token=existing.refresh_token if existing is not None else None,
            expires_at=existing.expires_at if existing is not None else None,
        ),
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
        connected=existing is not None
        and existing.status is MCPOAuthConnectionStatus.CONNECTED
        and (existing.access_token is not None),
    )
    _require_agent_item(store_result)
    return build_authorization_url(
        auth_url=metadata.authorization_endpoint,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=mcp_config.scopes,
        state=oauth_state,
        code_challenge=pkce.code_challenge,
        resource=mcp_config.server_url,
    )


async def exchange_agent(
    member: WorkspaceMember,
    service: ToolkitService,
    config: Config,
    registry: dict[str, ToolkitProvider[Any]],
    code: str,
    *,
    handle: str,
    agent_id: str,
    toolkit_config_id: str,
    state: str,
) -> None:
    """Exchange OAuth code for an Agent-owned Toolkit connection."""
    verified = verify_agent_toolkit_oauth_state(state, config.credential_encryption.key)
    expected_redirect_uri = (
        f"{config.web_url}/oauth/mcp/callback?handle={handle}&agent_id={agent_id}&toolkit_config_id={toolkit_config_id}"
        if config.web_url
        else ""
    )
    if (
        verified is None
        or verified.toolkit_id != toolkit_config_id
        or verified.workspace_id != member.workspace_id
        or (verified.agent_id != agent_id)
        or (verified.user_id != member.user_id)
        or (verified.redirect_uri != expected_redirect_uri)
        or (verified.callback_target != _AGENT_TOOLKIT_CALLBACK_TARGET)
    ):
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.INVALID_REQUEST,
            "OAuth state does not match Agent toolkit.",
        )
    context = await _get_agent_oauth_context(
        service, member, agent_id=agent_id, toolkit_config_id=toolkit_config_id
    )
    toolkit = context.toolkit
    connection = context.connection
    if connection is None:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
            "OAuth connection not found. Start connect again.",
        )
    mcp_config = helpers.resolve_mcp_config(
        toolkit.toolkit_type, toolkit.config, registry
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
        proxy_url=config.mcp_proxy_url,
        toolkit_id=toolkit_config_id,
        user_id=member.user_id,
    )
    store_result = await service.store_agent_oauth_connection(
        agent_id,
        toolkit_config_id,
        AgentToolkitOAuthConnectionInput(
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
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
        connected=True,
    )
    _require_agent_item(store_result)


async def test_agent_saved(
    member: WorkspaceMember,
    service: ToolkitService,
    config: Config,
    registry: dict[str, ToolkitProvider[Any]],
    *,
    agent_id: str,
    toolkit_config_id: str,
) -> TestConnectionResult:
    """Test one stored Agent-owned Toolkit connection."""
    toolkit = await _get_agent_toolkit(
        service, member, agent_id=agent_id, toolkit_config_id=toolkit_config_id
    )
    provider = registry.get(toolkit.toolkit_type)
    if provider is None:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.INVALID_REQUEST,
            f"Unknown toolkit type: {toolkit.toolkit_type}",
        )
    validated_config = provider.validate_config(toolkit.config)
    result = await provider.test_connection(
        validated_config, toolkit.credentials, proxy_url=config.mcp_proxy_url
    )
    return result


async def test_agent_unsaved(
    member: WorkspaceMember,
    service: ToolkitService,
    config: Config,
    platform_runtime: PlatformGitHubAppRuntimeService,
    registry: dict[str, ToolkitProvider[Any]],
    *,
    agent_id: str,
    request: ToolkitConnectionTestInput,
) -> TestConnectionResult:
    """Test unsaved Agent-owned Toolkit settings without creating a resource."""
    await authorize_agent_management(service, member, agent_id=agent_id)
    provider = registry.get(request.toolkit_type)
    if provider is None:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.INVALID_REQUEST,
            f"Unknown toolkit type: {request.toolkit_type}",
        )
    validated_config = provider.validate_config(request.config)
    credentials_json = await _resolve_agent_test_credentials(
        request,
        service,
        member,
        agent_id=agent_id,
    )
    credentials_json = await helpers.bind_platform_app_test_credentials(
        credentials_json, platform_runtime
    )
    result = await provider.test_connection(
        validated_config, credentials_json, proxy_url=config.mcp_proxy_url
    )
    return result


async def _get_agent_toolkit(
    service: ToolkitService,
    member: WorkspaceMember,
    *,
    agent_id: str,
    toolkit_config_id: str,
) -> ToolkitOutput:
    """Load one currently authorized Agent-owned Toolkit without disclosure."""
    result = await service.get_agent_owned(
        agent_id,
        toolkit_config_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    if not result.success:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND, "Toolkit config not found."
        )
    return result.value


async def _get_agent_oauth_context(
    service: ToolkitService,
    member: WorkspaceMember,
    *,
    agent_id: str,
    toolkit_config_id: str,
) -> AgentToolkitOAuthContext:
    """Load Agent-owned OAuth state through the authorization-aware service."""
    result = await service.get_agent_oauth_context(
        agent_id,
        toolkit_config_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    if not result.success:
        raise ToolkitOAuthError(
            ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND, "Toolkit config not found."
        )
    return result.value


async def authorize_agent_management(
    service: ToolkitService, member: WorkspaceMember, *, agent_id: str
) -> None:
    """Require current Agent management authority without exposing Toolkit state."""
    result = await service.authorize_agent_management(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    _require_agent_management(result)


def _require_agent_management(
    result: Result[None, AgentNotBelongToWorkspace | NotAdmin],
) -> None:
    """Map Agent-level management authorization without item disclosure."""
    if result.success:
        return
    error = result.error
    match error:
        case AgentNotBelongToWorkspace():
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND, "Agent not found."
            )
        case NotAdmin():
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.WRITE_PERMISSION_REQUIRED,
                "Agent administrator or workspace owner access required.",
            )
        case _:
            assert_never(error)


def _require_agent_item(
    result: Result[None, AgentNotBelongToWorkspace | NotAdmin | NotFound],
) -> None:
    """Map every Agent-owned item mismatch to the same 404 boundary."""
    if result.success:
        return
    raise ToolkitOAuthError(
        ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND, "Toolkit config not found."
    )


async def _resolve_agent_test_credentials(
    request: ToolkitConnectionTestInput,
    service: ToolkitService,
    member: WorkspaceMember,
    *,
    agent_id: str,
) -> str | None:
    """Merge saved Agent-owned credentials with unsaved non-empty values."""
    if request.toolkit_config_id is not None:
        toolkit = await _get_agent_toolkit(
            service,
            member,
            agent_id=agent_id,
            toolkit_config_id=request.toolkit_config_id,
        )
        return helpers.merge_saved_test_credentials(request, toolkit.credentials)
    if request.credentials is not None:
        return json.dumps(request.credentials)
    return None
