"""Personal MCP setup using common discovery/registration and exact owner callbacks."""

import dataclasses
import json
import secrets
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.github_credentials import GitHubSecretsAppPlatform
from azents.core.oauth2 import (
    PersonalToolkitOAuthState,
    build_authorization_url,
    create_personal_toolkit_oauth_state,
    generate_pkce_pair,
    verify_personal_toolkit_oauth_state,
)
from azents.core.personal_toolkit import (
    PersonalToolkitConfigurationConflict,
    PersonalToolkitManager,
)
from azents.core.tools import TestConnectionResult, ToolkitProvider
from azents.engine.tools.deps import get_toolkit_registry
from azents.repos.toolkit.personal_management import (
    PersonalToolkitManagementRepository,
    PersonalToolkitManagementSnapshot,
    PersonalToolkitPlatformTestAuthority,
)
from azents.repos.toolkit_operations.data import PlatformToolkitAuthority
from azents.repos.toolkit_operations.owned_data import OAuthConnectionWrite
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.toolkit_oauth import helpers
from azents.services.toolkit_oauth.data import (
    ToolkitConnectionTestInput,
    ToolkitOAuthError,
    ToolkitOAuthFailureReason,
)


@dataclasses.dataclass(frozen=True)
class PersonalToolkitOAuthService:
    """Close DB operations before Provider work; repeat authority before publication."""

    repository: Annotated[
        PersonalToolkitManagementRepository,
        Depends(PersonalToolkitManagementRepository),
    ]
    config: Annotated[Config, Depends(get_config)]
    registry: Annotated[dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)]
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()]

    async def test_saved(
        self,
        subject: PersonalToolkitManager,
        toolkit_id: str,
    ) -> TestConnectionResult:
        """Test exact-owner saved configuration through the common Provider method."""
        current = await self.repository.get(subject, toolkit_id)
        return await self._test_snapshot(
            subject,
            ToolkitConnectionTestInput(
                toolkit_type=current.toolkit.toolkit_type,
                config=current.toolkit.config,
                credentials=None,
                toolkit_config_id=toolkit_id,
            ),
            current,
        )

    async def test_unsaved(
        self,
        subject: PersonalToolkitManager,
        request: ToolkitConnectionTestInput,
    ) -> TestConnectionResult:
        """Reuse credential-edit merge and Provider tests without persisting drafts."""
        await self.repository.authorize(subject)
        current = (
            None
            if request.toolkit_config_id is None
            else await self.repository.get(subject, request.toolkit_config_id)
        )
        return await self._test_snapshot(subject, request, current)

    async def _test_snapshot(
        self,
        subject: PersonalToolkitManager,
        request: ToolkitConnectionTestInput,
        current: PersonalToolkitManagementSnapshot | None,
    ) -> TestConnectionResult:
        provider = self.registry.get(request.toolkit_type)
        if provider is None:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                "Unknown toolkit type.",
            )
        validated = provider.validate_config(request.config)
        if current is not None:
            if current.toolkit.toolkit_type != request.toolkit_type:
                raise ToolkitOAuthError(
                    ToolkitOAuthFailureReason.INVALID_REQUEST,
                    "Saved Toolkit type does not match the connection test.",
                )
            credentials = helpers.merge_saved_test_credentials(
                request,
                current.toolkit.credentials,
            )
        else:
            credentials = (
                json.dumps(request.credentials)
                if request.credentials is not None
                else None
            )
        prepared = await helpers.prepare_platform_app_test_credentials(
            credentials, self.platform_runtime
        )
        platform_authority = None
        if prepared.platform is not None:
            assert prepared.credentials_json is not None
            try:
                secrets = GitHubSecretsAppPlatform.model_validate_json(
                    prepared.credentials_json
                )
                installation_ids = frozenset(
                    int(item.installation_id) for item in secrets.installations
                )
            except ValueError:
                raise ToolkitOAuthError(
                    ToolkitOAuthFailureReason.INVALID_REQUEST,
                    "Invalid Platform GitHub installation credentials.",
                ) from None
            if current is not None and request.credentials is None:
                assert credentials is not None
                saved = GitHubSecretsAppPlatform.model_validate_json(credentials)
                if saved.app_id != prepared.platform.app_id:
                    raise PersonalToolkitConfigurationConflict(
                        "Platform GitHub App changed; reconnect before testing"
                    )
            platform_authority = PersonalToolkitPlatformTestAuthority(
                authority=PlatformToolkitAuthority(
                    app_id=secrets.app_id,
                    app_id_source=prepared.platform.app_id_source,
                    user_id=subject.user_id,
                    installation_ids=installation_ids,
                ),
                effective_generation=prepared.platform.effective_generation,
            )
        # Admit every selected installation before a Provider can exchange the
        # server App's credentials, including when testing an unsaved draft.
        await self.repository.authorize_test(
            subject,
            source=None if current is None else current.toolkit,
            platform=platform_authority,
        )
        return await provider.test_connection(
            validated,
            prepared.credentials_json,
            proxy_url=self.config.mcp_proxy_url,
        )

    async def connect(self, subject: PersonalToolkitManager, toolkit_id: str) -> str:
        """Prepare common MCP authentication without an owning Workspace surrogate."""
        current = await self.repository.read_oauth_context(subject, toolkit_id)
        handle = await self.repository.workspace_handle(subject)
        callback_target = urlencode(
            {"personal_toolkit_config_id": toolkit_id, "handle": handle}
        )
        redirect_uri = (
            f"{self.config.web_url}/oauth/mcp/callback?{callback_target}"
            if self.config.web_url
            else ""
        )
        prepared = await helpers.prepare_mcp_authorization(
            current.toolkit,
            current.connection,
            redirect_uri=redirect_uri,
            proxy_url=self.config.mcp_proxy_url,
            registry=self.registry,
        )
        published = await self.repository.store_oauth_connection(
            subject,
            toolkit_id,
            expected_revision=current.toolkit.revision,
            connection=prepared.connection,
        )
        pkce = generate_pkce_pair()
        state = create_personal_toolkit_oauth_state(
            PersonalToolkitOAuthState(
                type="personal_toolkit_oauth",
                owner=published.toolkit.owner,
                toolkit_id=toolkit_id,
                auth_session_id=subject.session_id,
                source_revision=published.toolkit.revision,
                redirect_uri=redirect_uri,
                code_verifier=pkce.code_verifier,
                nonce=secrets.token_urlsafe(16),
            ),
            self.config.credential_encryption.key,
        )
        return build_authorization_url(
            auth_url=prepared.connection.authorization_endpoint,
            client_id=prepared.connection.client_id,
            redirect_uri=redirect_uri,
            scopes=prepared.config.scopes,
            state=state,
            code_challenge=pkce.code_challenge,
            resource=prepared.config.server_url,
        )

    async def exchange(
        self,
        subject: PersonalToolkitManager,
        toolkit_id: str,
        *,
        code: str,
        state: str,
    ) -> None:
        """Admit only the initiating owner/Auth Session and unchanged setup source."""
        verified = verify_personal_toolkit_oauth_state(
            state,
            self.config.credential_encryption.key,
        )
        if verified is None or (
            verified.toolkit_id != toolkit_id
            or verified.owner.user_id != subject.user_id
            or verified.owner.workspace_id != subject.workspace_id
            or verified.auth_session_id != subject.session_id
        ):
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                "OAuth state does not match personal Toolkit authorization",
            )
        current = await self.repository.read_oauth_context(subject, toolkit_id)
        if current.toolkit.revision != verified.source_revision:
            raise PersonalToolkitConfigurationConflict(
                "Personal Toolkit changed; restart authorization"
            )
        connection = current.connection
        if connection is None:
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND,
                "OAuth connection not found. Start connect again.",
            )
        mcp_config = helpers.resolve_mcp_config(
            current.toolkit.toolkit_type, current.toolkit.config, self.registry
        )
        if mcp_config.auth_type != "oauth2":
            raise ToolkitOAuthError(
                ToolkitOAuthFailureReason.INVALID_REQUEST,
                "Toolkit does not use OAuth2 authentication.",
            )
        token = await helpers.exchange_and_handle_errors(
            token_url=connection.token_endpoint,
            client_id=connection.client_id,
            client_secret=connection.client_secret,
            code=code,
            redirect_uri=verified.redirect_uri,
            code_verifier=verified.code_verifier,
            resource=connection.resource or mcp_config.server_url,
            proxy_url=self.config.mcp_proxy_url,
            toolkit_id=toolkit_id,
            user_id=subject.user_id,
        )
        await self.repository.store_oauth_connection(
            subject,
            toolkit_id,
            expected_revision=verified.source_revision,
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
                access_token=token.access_token,
                refresh_token=token.refresh_token,
                expires_at=token.expires_at,
            ),
        )

    async def disconnect(
        self, subject: PersonalToolkitManager, toolkit_id: str
    ) -> None:
        """Delete local MCP credentials and invalidate pending personal callbacks."""
        await self.repository.delete_oauth_connection(subject, toolkit_id)
