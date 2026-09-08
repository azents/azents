"""Toolkit service."""

import dataclasses
import json
from typing import Annotated, Any, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import (
    AgentLifecycleStatus,
    MCPOAuthConnectionStatus,
    ToolkitScopeType,
    WorkspaceUserRole,
)
from azents.core.github_credentials import GitHubSecrets, GitHubSecretsAppPlatform
from azents.core.mcp_credentials import McpSecrets
from azents.core.tools import McpToolkitConfig, ToolkitProvider, ToolkitType
from azents.engine.tools.deps import get_toolkit_registry
from azents.engine.tools.envvar import EnvVarToolkitSecrets
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.toolkit import (
    AgentToolkitRepository,
    ToolkitRepository,
    ToolkitScopeRepository,
)
from azents.repos.toolkit.data import (
    AgentToolkitCreate,
    DuplicateAgentToolkit,
    DuplicateScope,
    NotFound,
    ScopeNotFound,
    ToolkitCreate,
    ToolkitScopeCreate,
    ToolkitUpdate,
)
from azents.repos.toolkit.data import (
    DuplicateSlug as RepoDuplicateSlug,
)
from azents.services.agent.data import NotAdmin
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)

from .data import (
    AgentNotBelongToWorkspace,
    AgentToolkitListOutput,
    AgentToolkitManagementItemOutput,
    AgentToolkitManagementOutput,
    AgentToolkitNotBelongToAgent,
    AgentToolkitOAuthConnectionInput,
    AgentToolkitOAuthContext,
    AgentToolkitOutput,
    DuplicateSlug,
    EffectiveSlugConflict,
    InvalidConfig,
    InvalidCredentials,
    InvalidToolkitType,
    NotBelongToWorkspace,
    ScopeNotBelongToToolkit,
    ToolkitCreateInput,
    ToolkitListOutput,
    ToolkitNotAvailable,
    ToolkitOutput,
    ToolkitReadiness,
    ToolkitScopeCreateInput,
    ToolkitScopeListOutput,
    ToolkitScopeOutput,
    ToolkitUpdateInput,
)

_mcp_secrets_adapter: TypeAdapter[McpSecrets] = TypeAdapter(McpSecrets)
_github_secrets_adapter: TypeAdapter[GitHubSecrets] = TypeAdapter(GitHubSecrets)
_envvar_secrets_adapter: TypeAdapter[EnvVarToolkitSecrets] = TypeAdapter(
    EnvVarToolkitSecrets
)


def _resolve_mcp_config(
    toolkit_type: str,
    config: dict[str, Any],
    registry: dict[str, ToolkitProvider[Any]],
) -> McpToolkitConfig | None:
    """Resolve a toolkit config into MCP config when supported."""
    provider = registry.get(toolkit_type)
    if provider is None:
        return None
    try:
        typed_config = provider.validate_config(config)
        return provider.to_mcp_config(typed_config)
    except ValidationError:
        return None


def merge_envvar_credentials(
    existing_credentials: str | None,
    submitted_credentials: dict[str, object],
    config: dict[str, Any],
) -> dict[str, object]:
    """Merge non-empty EnvVar edits into values allowed by current config."""
    submitted = _envvar_secrets_adapter.validate_python(submitted_credentials)
    existing_values: dict[str, str] = {}
    if existing_credentials is not None:
        try:
            existing_values = _envvar_secrets_adapter.validate_json(
                existing_credentials
            ).values
        except ValidationError:
            pass

    merged_values = dict(existing_values)
    merged_values.update(
        {name: value for name, value in submitted.values.items() if value != ""}
    )
    raw_entries = config.get("entries")
    entry_names = (
        {
            entry["name"]
            for entry in raw_entries
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        }
        if isinstance(raw_entries, list)
        else set()
    )
    return {
        "values": {
            name: value for name, value in merged_values.items() if name in entry_names
        }
    }


def _get_toolkit_repo(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> ToolkitRepository:
    """ToolkitRepository dependency."""
    return ToolkitRepository(cipher=cipher)


def _get_mcp_oauth_connection_repo(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> MCPOAuthConnectionRepository:
    """MCPOAuthConnectionRepository dependency."""
    return MCPOAuthConnectionRepository(cipher=cipher)


@dataclasses.dataclass
class ToolkitService:
    """Toolkit CRUD + Scope management + AgentToolkit management service."""

    toolkit_repo: Annotated[ToolkitRepository, Depends(_get_toolkit_repo)]
    mcp_oauth_connection_repo: Annotated[
        MCPOAuthConnectionRepository, Depends(_get_mcp_oauth_connection_repo)
    ]
    scope_repo: Annotated[ToolkitScopeRepository, Depends()]
    agent_toolkit_repo: Annotated[AgentToolkitRepository, Depends()]
    agent_repo: Annotated[AgentRepository, Depends()]
    agent_admin_repo: Annotated[AgentAdminRepository, Depends()]
    github_user_installation_repo: Annotated[
        GithubUserInstallationRepository, Depends()
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    toolkit_registry: Annotated[
        dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)
    ]
    github_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()]

    # ------------------------------------------------------------------ #
    # Toolkit CRUD (for Manager)
    # ------------------------------------------------------------------ #

    async def create(
        self, create: ToolkitCreateInput, *, user_id: str
    ) -> Result[
        ToolkitOutput,
        InvalidToolkitType | InvalidConfig | DuplicateSlug | InvalidCredentials,
    ]:
        """Create Toolkit and automatically add workspace scope.

        :param create: Create data
        :param user_id: User ID
        :return: Created Toolkit or error
        """
        slug_error = self._validate_toolkit_type(create.toolkit_type)
        if slug_error is not None:
            return Failure(slug_error)

        config_error = self._validate_config(create.toolkit_type, create.config)
        if config_error is not None:
            return Failure(config_error)

        credentials = await self._bind_platform_app_identity(create.credentials)
        if isinstance(credentials, InvalidCredentials):
            return Failure(credentials)
        cred_error = self._validate_credentials(create.toolkit_type, credentials)
        if cred_error is not None:
            return Failure(cred_error)

        # Validate credentials by provider (e.g. GitHub installation ownership)
        provider = self.toolkit_registry.get(create.toolkit_type)
        if provider is not None:
            async with self.session_manager() as session:
                cred_err_msg = await provider.validate_credentials(
                    session, user_id, credentials
                )
            if cred_err_msg is not None:
                return Failure(InvalidCredentials(cred_err_msg))

        # Use toolkit_type as default when slug is unspecified
        slug = create.slug if create.slug is not None else create.toolkit_type

        credentials_json: str | None = None
        if credentials is not None:
            credentials_json = json.dumps(credentials)

        repo_create = ToolkitCreate(
            workspace_id=create.workspace_id,
            owner_agent_id=None,
            toolkit_type=create.toolkit_type,
            slug=slug,
            name=create.name,
            description=create.description,
            config=create.config,
            prompt=create.prompt,
            credentials=credentials_json,
            enabled=create.enabled,
            always_expose_tools=create.always_expose_tools,
        )
        async with self.session_manager() as session:
            result = await self.toolkit_repo.create(session, repo_create)
            match result:
                case Success(toolkit):
                    # Automatically create workspace scope
                    await self.scope_repo.create(
                        session,
                        ToolkitScopeCreate(
                            toolkit_id=toolkit.id,
                            scope_type=ToolkitScopeType.WORKSPACE,
                            scope_id=create.workspace_id,
                        ),
                    )
                    output = ToolkitOutput.model_validate(toolkit, from_attributes=True)
                    return Success(await self._attach_oauth_connection(output))
                case Failure(error):
                    return Failure(DuplicateSlug(slug=error.slug))
                case _:
                    assert_never(result)

    async def list_by_workspace(self, workspace_id: str) -> ToolkitListOutput:
        """Fetch all Toolkits in workspace.

        :param workspace_id: Workspace ID
        :return: Toolkit list
        """
        async with self.session_manager() as session:
            toolkits = await self.toolkit_repo.list_by_workspace(session, workspace_id)
        outputs = [
            ToolkitOutput.model_validate(t, from_attributes=True) for t in toolkits
        ]
        return ToolkitListOutput(items=await self._attach_oauth_connections(outputs))

    async def get_by_id(
        self, toolkit_id: str, *, workspace_id: str
    ) -> Result[ToolkitOutput, NotFound | NotBelongToWorkspace]:
        """Fetch Toolkit by ID.

        Includes workspace isolation validation.

        :param toolkit_id: Toolkit ID
        :param workspace_id: Workspace ID
        :return: Toolkit or error
        """
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_shared_by_id(session, toolkit_id)
        if toolkit is None:
            return Failure(NotFound(toolkit_id=toolkit_id))
        if toolkit.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(toolkit_id=toolkit_id))
        output = ToolkitOutput.model_validate(toolkit, from_attributes=True)
        return Success(await self._attach_oauth_connection(output))

    async def update_by_id(
        self,
        toolkit_id: str,
        update: ToolkitUpdateInput,
        *,
        workspace_id: str,
        user_id: str,
    ) -> Result[
        ToolkitOutput,
        NotFound
        | NotBelongToWorkspace
        | InvalidConfig
        | DuplicateSlug
        | EffectiveSlugConflict
        | InvalidCredentials,
    ]:
        """Update Toolkit by ID.

        :param toolkit_id: Toolkit ID
        :param update: Update data
        :param workspace_id: Workspace ID
        :param user_id: User ID
        :return: Updated Toolkit or error
        """
        async with self.session_manager() as session:
            existing = await self.toolkit_repo.get_shared_by_id(session, toolkit_id)
        if existing is None:
            return Failure(NotFound(toolkit_id=toolkit_id))
        if existing.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(toolkit_id=toolkit_id))

        if "config" in update:
            config_error = self._validate_config(
                existing.toolkit_type, update["config"]
            )
            if config_error is not None:
                return Failure(config_error)

        normalized_credentials: dict[str, object] | None = None
        if "credentials" in update:
            update_credentials = update["credentials"]
            if update_credentials is not None:
                bound_credentials = await self._bind_platform_app_identity(
                    update_credentials
                )
                if isinstance(bound_credentials, InvalidCredentials):
                    return Failure(bound_credentials)
                normalized_credentials = bound_credentials
                if existing.toolkit_type == ToolkitType.ENVVAR:
                    if normalized_credentials is None:
                        return Failure(
                            InvalidCredentials(
                                "EnvVar credential updates require credentials."
                            )
                        )
                    config = update["config"] if "config" in update else existing.config
                    normalized_credentials = merge_envvar_credentials(
                        existing.credentials,
                        normalized_credentials,
                        config,
                    )
                cred_error = self._validate_credentials(
                    existing.toolkit_type,
                    normalized_credentials,
                )
                if cred_error is not None:
                    return Failure(cred_error)
                provider = self.toolkit_registry.get(existing.toolkit_type)
                if provider is not None:
                    async with self.session_manager() as session:
                        cred_err_msg = await provider.validate_credentials(
                            session,
                            user_id,
                            normalized_credentials,
                        )
                    if cred_err_msg is not None:
                        return Failure(InvalidCredentials(cred_err_msg))
        elif (
            existing.toolkit_type == ToolkitType.ENVVAR
            and "config" in update
            and existing.credentials is not None
        ):
            normalized_credentials = merge_envvar_credentials(
                existing.credentials,
                {"values": {}},
                update["config"],
            )

        repo_update = ToolkitUpdate()
        if "slug" in update:
            repo_update["slug"] = update["slug"]
        if "name" in update:
            repo_update["name"] = update["name"]
        if "description" in update:
            repo_update["description"] = update["description"]
        if "config" in update:
            repo_update["config"] = update["config"]
        if "prompt" in update:
            repo_update["prompt"] = update["prompt"]
        if "credentials" in update or normalized_credentials is not None:
            repo_update["credentials"] = (
                json.dumps(normalized_credentials)
                if normalized_credentials is not None
                else None
            )
        if "enabled" in update:
            repo_update["enabled"] = update["enabled"]
        if "always_expose_tools" in update:
            repo_update["always_expose_tools"] = update["always_expose_tools"]

        # Delete existing credentials when auth_type changes
        if "config" in update and "credentials" not in update:
            old_auth = existing.config.get("auth_type") if existing.config else None
            new_auth = update["config"].get("auth_type") if update["config"] else None
            if old_auth != new_auth and new_auth is not None:
                repo_update["credentials"] = None

        async with self.session_manager() as session:
            locked = await self.toolkit_repo.get_shared_by_id_for_update(
                session,
                toolkit_id,
            )
            if locked is None:
                return Failure(NotFound(toolkit_id=toolkit_id))
            if locked.workspace_id != workspace_id:
                return Failure(NotBelongToWorkspace(toolkit_id=toolkit_id))

            candidate_slug = repo_update.get("slug", locked.slug)
            candidate_enabled = repo_update.get("enabled", locked.enabled)
            namespace_change = (
                candidate_slug != locked.slug or candidate_enabled != locked.enabled
            )
            if namespace_change:
                agent_ids = await self.agent_toolkit_repo.list_agent_ids_by_toolkit(
                    session,
                    toolkit_id,
                )
                for attached_agent_id in agent_ids:
                    await self.agent_repo.lock_by_id(session, attached_agent_id)
                for attached_agent_id in agent_ids:
                    if await self.toolkit_repo.has_effective_slug_conflict(
                        session,
                        agent_id=attached_agent_id,
                        workspace_id=workspace_id,
                        toolkit_id=toolkit_id,
                        slug=candidate_slug,
                        enabled=candidate_enabled,
                    ):
                        return Failure(EffectiveSlugConflict(slug=candidate_slug))

            result = await self.toolkit_repo.update_by_id(
                session,
                toolkit_id,
                repo_update,
            )
        match result:
            case Success(value):
                output = ToolkitOutput.model_validate(value, from_attributes=True)
                return Success(await self._attach_oauth_connection(output))
            case Failure(error):
                if isinstance(error, RepoDuplicateSlug):
                    return Failure(DuplicateSlug(slug=error.slug))
                return Failure(error)

    async def delete_by_id(
        self, toolkit_id: str, *, workspace_id: str
    ) -> Result[None, NotFound | NotBelongToWorkspace]:
        """Delete Toolkit by ID.

        :param toolkit_id: Toolkit ID
        :param workspace_id: Workspace ID
        :return: Success or error
        """
        async with self.session_manager() as session:
            existing = await self.toolkit_repo.get_shared_by_id(session, toolkit_id)
        if existing is None:
            return Failure(NotFound(toolkit_id=toolkit_id))
        if existing.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(toolkit_id=toolkit_id))

        async with self.session_manager() as session:
            await self.toolkit_repo.delete_by_id(session, toolkit_id)
        return Success(None)

    # ------------------------------------------------------------------ #
    # Agent-owned Toolkit management (Owner or explicit AgentAdmin)
    # ------------------------------------------------------------------ #

    async def list_agent_management(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentToolkitManagementOutput,
        AgentNotBelongToWorkspace | NotAdmin,
    ]:
        """Build the authorized Agent Toolkit management projection."""
        async with self.session_manager() as session:
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=False,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)

            attachments = await self.agent_toolkit_repo.list_by_agent(
                session,
                agent_id,
            )
            shared_pairs = [
                (
                    attachment,
                    await self.toolkit_repo.get_shared_by_id(
                        session,
                        attachment.toolkit_id,
                    ),
                )
                for attachment in attachments
            ]
            owned = await self.toolkit_repo.list_by_owner_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
            )
            available = await self.toolkit_repo.list_available_for_workspace_user(
                session,
                workspace_id,
                user_id,
            )

        attached_ids = {attachment.toolkit_id for attachment in attachments}
        shared_outputs = await self._attach_oauth_connections(
            [
                ToolkitOutput.model_validate(toolkit, from_attributes=True)
                for _, toolkit in shared_pairs
                if toolkit is not None
            ]
        )
        shared_output_by_id = {toolkit.id: toolkit for toolkit in shared_outputs}
        owned_outputs = await self._attach_oauth_connections(
            [
                ToolkitOutput.model_validate(toolkit, from_attributes=True)
                for toolkit in owned
            ]
        )
        available_outputs = await self._attach_oauth_connections(
            [
                ToolkitOutput.model_validate(toolkit, from_attributes=True)
                for toolkit in available
                if toolkit.id not in attached_ids
            ]
        )
        items = [
            AgentToolkitManagementItemOutput(
                ownership_scope="workspace_shared",
                toolkit=shared_output_by_id[attachment.toolkit_id],
                agent_toolkit_id=attachment.id,
                readiness=self._readiness(shared_output_by_id[attachment.toolkit_id]),
            )
            for attachment in attachments
            if attachment.toolkit_id in shared_output_by_id
        ]
        items.extend(
            AgentToolkitManagementItemOutput(
                ownership_scope="agent_only",
                toolkit=toolkit,
                agent_toolkit_id=None,
                readiness=self._readiness(toolkit),
            )
            for toolkit in owned_outputs
        )
        return Success(
            AgentToolkitManagementOutput(
                items=items,
                available_shared=available_outputs,
            )
        )

    async def authorize_agent_management(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[None, AgentNotBelongToWorkspace | NotAdmin]:
        """Verify current Agent Toolkit management authority."""
        async with self.session_manager() as session:
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=False,
            )
        match access:
            case Success():
                return Success(None)
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access)

    async def sync_agent_github_installations(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
        platform_app_id: str,
        installations: list[dict[str, object]],
    ) -> Result[None, AgentNotBelongToWorkspace | NotAdmin]:
        """Synchronize GitHub installations after current Agent authorization."""
        async with self.session_manager() as session:
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=False,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)
            await self.github_user_installation_repo.sync(
                session,
                user_id,
                platform_app_id,
                installations,
            )
        return Success(None)

    async def get_agent_oauth_context(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentToolkitOAuthContext,
        AgentNotBelongToWorkspace | NotAdmin | NotFound,
    ]:
        """Load one authorized Agent-owned Toolkit and OAuth connection."""
        async with self.session_manager() as session:
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=False,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)
            toolkit = await self.toolkit_repo.get_agent_owned_by_id(
                session,
                toolkit_id,
                agent_id=agent_id,
            )
            if toolkit is None or toolkit.workspace_id != workspace_id:
                return Failure(NotFound(toolkit_id=toolkit_id))
            connection = await self.mcp_oauth_connection_repo.get_by_toolkit_id(
                session,
                toolkit_id,
            )
        return Success(
            AgentToolkitOAuthContext(
                toolkit=ToolkitOutput.model_validate(toolkit, from_attributes=True),
                connection=connection,
            )
        )

    async def store_agent_oauth_connection(
        self,
        agent_id: str,
        toolkit_id: str,
        connection: AgentToolkitOAuthConnectionInput,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        connected: bool,
    ) -> Result[
        None,
        AgentNotBelongToWorkspace | NotAdmin | NotFound,
    ]:
        """Persist OAuth state only while Agent ownership and authority remain valid."""
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_by_id_for_update(
                session,
                toolkit_id,
            )
            if (
                toolkit is None
                or toolkit.owner_agent_id != agent_id
                or toolkit.workspace_id != workspace_id
            ):
                return Failure(NotFound(toolkit_id=toolkit_id))
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=True,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)
            await self.mcp_oauth_connection_repo.upsert_connected(
                session,
                toolkit_id=toolkit_id,
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
                access_token=connection.access_token,
                refresh_token=connection.refresh_token,
                expires_at=connection.expires_at,
            )
            if not connected:
                await self.mcp_oauth_connection_repo.mark_reconnect_required(
                    session,
                    toolkit_id=toolkit_id,
                )
        return Success(None)

    async def delete_agent_oauth_connection(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        None,
        AgentNotBelongToWorkspace | NotAdmin | NotFound,
    ]:
        """Delete OAuth state only for the currently authorized Agent-owned Toolkit."""
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_by_id_for_update(
                session,
                toolkit_id,
            )
            if (
                toolkit is None
                or toolkit.owner_agent_id != agent_id
                or toolkit.workspace_id != workspace_id
            ):
                return Failure(NotFound(toolkit_id=toolkit_id))
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=True,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)
            await self.mcp_oauth_connection_repo.delete_by_toolkit_id(
                session,
                toolkit_id,
            )
        return Success(None)

    async def create_agent_owned(
        self,
        agent_id: str,
        create: ToolkitCreateInput,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        ToolkitOutput,
        AgentNotBelongToWorkspace
        | NotAdmin
        | InvalidToolkitType
        | InvalidConfig
        | DuplicateSlug
        | EffectiveSlugConflict
        | InvalidCredentials,
    ]:
        """Create an Agent-owned ToolkitConfig without a scope or attachment."""
        async with self.session_manager() as session:
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=False,
            )
        match access:
            case Failure(error):
                return Failure(error)
            case Success():
                pass
            case _:
                assert_never(access)

        type_error = self._validate_toolkit_type(create.toolkit_type)
        if type_error is not None:
            return Failure(type_error)
        config_error = self._validate_config(create.toolkit_type, create.config)
        if config_error is not None:
            return Failure(config_error)
        credentials = await self._bind_platform_app_identity(create.credentials)
        if isinstance(credentials, InvalidCredentials):
            return Failure(credentials)
        credential_error = self._validate_credentials(
            create.toolkit_type,
            credentials,
        )
        if credential_error is not None:
            return Failure(credential_error)
        provider = self.toolkit_registry.get(create.toolkit_type)
        if provider is not None:
            async with self.session_manager() as session:
                detail = await provider.validate_credentials(
                    session,
                    user_id,
                    credentials,
                )
            if detail is not None:
                return Failure(InvalidCredentials(detail))

        slug = create.slug if create.slug is not None else create.toolkit_type
        credentials_json = json.dumps(credentials) if credentials is not None else None
        async with self.session_manager() as session:
            locked_access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=True,
            )
            match locked_access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(locked_access)
            if await self.toolkit_repo.has_effective_slug_conflict(
                session,
                agent_id=agent_id,
                workspace_id=workspace_id,
                toolkit_id="",
                slug=slug,
                enabled=create.enabled,
            ):
                return Failure(EffectiveSlugConflict(slug=slug))
            result = await self.toolkit_repo.create(
                session,
                ToolkitCreate(
                    workspace_id=workspace_id,
                    owner_agent_id=agent_id,
                    toolkit_type=create.toolkit_type,
                    slug=slug,
                    name=create.name,
                    description=create.description,
                    config=create.config,
                    prompt=create.prompt,
                    credentials=credentials_json,
                    enabled=create.enabled,
                    always_expose_tools=create.always_expose_tools,
                ),
            )
        match result:
            case Success(toolkit):
                output = ToolkitOutput.model_validate(toolkit, from_attributes=True)
                return Success(await self._attach_oauth_connection(output))
            case Failure(error):
                return Failure(DuplicateSlug(slug=error.slug))
            case _:
                assert_never(result)

    async def get_agent_owned(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        ToolkitOutput,
        AgentNotBelongToWorkspace | NotAdmin | NotFound,
    ]:
        """Read one ToolkitConfig owned by the exact managed Agent."""
        async with self.session_manager() as session:
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=False,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)
            toolkit = await self.toolkit_repo.get_agent_owned_by_id(
                session,
                toolkit_id,
                agent_id=agent_id,
            )
        if toolkit is None or toolkit.workspace_id != workspace_id:
            return Failure(NotFound(toolkit_id=toolkit_id))
        output = ToolkitOutput.model_validate(toolkit, from_attributes=True)
        return Success(await self._attach_oauth_connection(output))

    async def update_agent_owned(
        self,
        agent_id: str,
        toolkit_id: str,
        update: ToolkitUpdateInput,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        ToolkitOutput,
        AgentNotBelongToWorkspace
        | NotAdmin
        | NotFound
        | InvalidConfig
        | DuplicateSlug
        | EffectiveSlugConflict
        | InvalidCredentials,
    ]:
        """Update one ToolkitConfig owned by the exact managed Agent."""
        existing_result = await self.get_agent_owned(
            agent_id,
            toolkit_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        match existing_result:
            case Failure(error):
                return Failure(error)
            case Success(existing):
                pass
            case _:
                assert_never(existing_result)

        if "config" in update:
            config_error = self._validate_config(
                existing.toolkit_type,
                update["config"],
            )
            if config_error is not None:
                return Failure(config_error)

        normalized_credentials: dict[str, object] | None = None
        if "credentials" in update:
            submitted = update["credentials"]
            if submitted is not None:
                bound = await self._bind_platform_app_identity(submitted)
                if isinstance(bound, InvalidCredentials):
                    return Failure(bound)
                normalized_credentials = bound
                if existing.toolkit_type == ToolkitType.ENVVAR:
                    if normalized_credentials is None:
                        return Failure(
                            InvalidCredentials(
                                "EnvVar credential updates require credentials."
                            )
                        )
                    config = update["config"] if "config" in update else existing.config
                    normalized_credentials = merge_envvar_credentials(
                        existing.credentials,
                        normalized_credentials,
                        config,
                    )
                credential_error = self._validate_credentials(
                    existing.toolkit_type,
                    normalized_credentials,
                )
                if credential_error is not None:
                    return Failure(credential_error)
                provider = self.toolkit_registry.get(existing.toolkit_type)
                if provider is not None:
                    async with self.session_manager() as session:
                        detail = await provider.validate_credentials(
                            session,
                            user_id,
                            normalized_credentials,
                        )
                    if detail is not None:
                        return Failure(InvalidCredentials(detail))
        elif (
            existing.toolkit_type == ToolkitType.ENVVAR
            and "config" in update
            and existing.credentials is not None
        ):
            normalized_credentials = merge_envvar_credentials(
                existing.credentials,
                {"values": {}},
                update["config"],
            )

        repo_update = ToolkitUpdate()
        if "slug" in update:
            repo_update["slug"] = update["slug"]
        if "name" in update:
            repo_update["name"] = update["name"]
        if "description" in update:
            repo_update["description"] = update["description"]
        if "config" in update:
            repo_update["config"] = update["config"]
        if "prompt" in update:
            repo_update["prompt"] = update["prompt"]
        if "enabled" in update:
            repo_update["enabled"] = update["enabled"]
        if "always_expose_tools" in update:
            repo_update["always_expose_tools"] = update["always_expose_tools"]
        if "credentials" in update or normalized_credentials is not None:
            repo_update["credentials"] = (
                json.dumps(normalized_credentials)
                if normalized_credentials is not None
                else None
            )
        if "config" in update and "credentials" not in update:
            old_auth = existing.config.get("auth_type") if existing.config else None
            new_auth = update["config"].get("auth_type") if update["config"] else None
            if old_auth != new_auth and new_auth is not None:
                repo_update["credentials"] = None

        async with self.session_manager() as session:
            locked = await self.toolkit_repo.get_by_id_for_update(
                session,
                toolkit_id,
            )
            if (
                locked is None
                or locked.owner_agent_id != agent_id
                or locked.workspace_id != workspace_id
            ):
                return Failure(NotFound(toolkit_id=toolkit_id))
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=True,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)
            candidate_slug = repo_update.get("slug", locked.slug)
            candidate_enabled = repo_update.get("enabled", locked.enabled)
            if await self.toolkit_repo.has_effective_slug_conflict(
                session,
                agent_id=agent_id,
                workspace_id=workspace_id,
                toolkit_id=toolkit_id,
                slug=candidate_slug,
                enabled=candidate_enabled,
            ):
                return Failure(EffectiveSlugConflict(slug=candidate_slug))
            result = await self.toolkit_repo.update_by_id(
                session,
                toolkit_id,
                repo_update,
            )
        match result:
            case Success(toolkit):
                output = ToolkitOutput.model_validate(toolkit, from_attributes=True)
                return Success(await self._attach_oauth_connection(output))
            case Failure(error):
                if isinstance(error, RepoDuplicateSlug):
                    return Failure(DuplicateSlug(slug=error.slug))
                return Failure(error)

    async def delete_agent_owned(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        None,
        AgentNotBelongToWorkspace | NotAdmin | NotFound,
    ]:
        """Delete one ToolkitConfig owned by the exact managed Agent."""
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_by_id_for_update(
                session,
                toolkit_id,
            )
            if (
                toolkit is None
                or toolkit.owner_agent_id != agent_id
                or toolkit.workspace_id != workspace_id
            ):
                return Failure(NotFound(toolkit_id=toolkit_id))
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=True,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)
            await self.toolkit_repo.delete_by_id(session, toolkit_id)
        return Success(None)

    # ------------------------------------------------------------------ #
    # Scope management (for Manager)
    # ------------------------------------------------------------------ #

    async def create_scope(
        self, create: ToolkitScopeCreateInput, *, workspace_id: str
    ) -> Result[ToolkitScopeOutput, NotFound | NotBelongToWorkspace | DuplicateScope]:
        """Create Toolkit Scope.

        :param create: Create data
        :param workspace_id: Workspace ID
        :return: Created ToolkitScope or error
        """
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_shared_by_id(
                session, create.toolkit_id
            )
        if toolkit is None:
            return Failure(NotFound(toolkit_id=create.toolkit_id))
        if toolkit.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(toolkit_id=create.toolkit_id))

        repo_create = ToolkitScopeCreate(
            toolkit_id=create.toolkit_id,
            scope_type=ToolkitScopeType.WORKSPACE,
            scope_id=workspace_id,
        )
        async with self.session_manager() as session:
            result = await self.scope_repo.create(session, repo_create)
        match result:
            case Success(value):
                return Success(
                    ToolkitScopeOutput.model_validate(value, from_attributes=True)
                )
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def list_scopes(
        self, toolkit_id: str, *, workspace_id: str
    ) -> Result[ToolkitScopeListOutput, NotFound | NotBelongToWorkspace]:
        """Fetch Scope list of Toolkit.

        :param toolkit_id: Toolkit ID
        :param workspace_id: Workspace ID
        :return: ToolkitScope list or error
        """
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_shared_by_id(session, toolkit_id)
        if toolkit is None:
            return Failure(NotFound(toolkit_id=toolkit_id))
        if toolkit.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(toolkit_id=toolkit_id))

        async with self.session_manager() as session:
            scopes = await self.scope_repo.list_by_toolkit(session, toolkit_id)
        return Success(
            ToolkitScopeListOutput(
                items=[
                    ToolkitScopeOutput.model_validate(s, from_attributes=True)
                    for s in scopes
                ]
            )
        )

    async def delete_scope(
        self,
        scope_id: str,
        *,
        toolkit_id: str,
        workspace_id: str,
    ) -> Result[
        None, NotFound | NotBelongToWorkspace | ScopeNotFound | ScopeNotBelongToToolkit
    ]:
        """Delete Toolkit Scope.

        :param scope_id: Scope ID
        :param toolkit_id: Toolkit ID
        :param workspace_id: Workspace ID
        :return: Success or error
        """
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_shared_by_id(session, toolkit_id)
        if toolkit is None:
            return Failure(NotFound(toolkit_id=toolkit_id))
        if toolkit.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(toolkit_id=toolkit_id))

        async with self.session_manager() as session:
            scope = await self.scope_repo.get_by_id(session, scope_id)
        if scope is None:
            return Failure(ScopeNotFound(scope_id=scope_id))
        if scope.toolkit_id != toolkit_id:
            return Failure(ScopeNotBelongToToolkit(scope_id=scope_id))

        async with self.session_manager() as session:
            await self.scope_repo.delete_by_id(session, scope_id)
        return Success(None)

    # ------------------------------------------------------------------ #
    # Agent Toolkit (for Member)
    # ------------------------------------------------------------------ #

    async def list_available(
        self, workspace_id: str, user_id: str
    ) -> ToolkitListOutput:
        """Fetch Toolkits available to workspace user.

        :param workspace_id: Workspace ID
        :param user_id: User ID
        :return: Available Toolkit list
        """
        async with self.session_manager() as session:
            toolkits = await self.toolkit_repo.list_available_for_workspace_user(
                session, workspace_id, user_id
            )
        outputs = [
            ToolkitOutput.model_validate(t, from_attributes=True) for t in toolkits
        ]
        return ToolkitListOutput(items=await self._attach_oauth_connections(outputs))

    async def list_agent_toolkits(
        self, agent_id: str, *, workspace_id: str
    ) -> Result[AgentToolkitListOutput, AgentNotBelongToWorkspace]:
        """Fetch Toolkit list mounted on agent.

        :param agent_id: Agent ID
        :param workspace_id: Workspace ID
        :return: AgentToolkit list or error
        """
        agent_error = await self._check_agent_workspace(agent_id, workspace_id)
        if agent_error is not None:
            return Failure(agent_error)

        async with self.session_manager() as session:
            agent_toolkits = await self.agent_toolkit_repo.list_by_agent(
                session, agent_id
            )
        return Success(
            AgentToolkitListOutput(
                items=[
                    AgentToolkitOutput.model_validate(at, from_attributes=True)
                    for at in agent_toolkits
                ]
            )
        )

    async def attach_to_agent(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        user_id: str,
    ) -> Result[
        AgentToolkitOutput,
        NotFound
        | NotBelongToWorkspace
        | ToolkitNotAvailable
        | DuplicateAgentToolkit
        | EffectiveSlugConflict
        | AgentNotBelongToWorkspace,
    ]:
        """Mount Toolkit on agent.

        :param agent_id: Agent ID
        :param toolkit_id: Toolkit ID
        :param workspace_id: Workspace ID
        :param user_id: Requesting user ID
        :return: Created AgentToolkit or error
        """
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_shared_by_id_for_update(
                session,
                toolkit_id,
            )
            if toolkit is None:
                return Failure(NotFound(toolkit_id=toolkit_id))
            if toolkit.workspace_id != workspace_id:
                return Failure(NotBelongToWorkspace(toolkit_id=toolkit_id))

            agent = await self.agent_repo.lock_by_id(session, agent_id)
            if agent is None or agent.workspace_id != workspace_id:
                return Failure(AgentNotBelongToWorkspace(agent_id=agent_id))

            available = await self.toolkit_repo.list_available_for_workspace_user(
                session,
                workspace_id,
                user_id,
            )
            available_ids = {item.id for item in available}
            if toolkit_id not in available_ids:
                return Failure(ToolkitNotAvailable(toolkit_id=toolkit_id))

            if await self.toolkit_repo.has_effective_slug_conflict(
                session,
                agent_id=agent_id,
                workspace_id=workspace_id,
                toolkit_id=toolkit_id,
                slug=toolkit.slug,
                enabled=toolkit.enabled,
            ):
                return Failure(EffectiveSlugConflict(slug=toolkit.slug))

            repo_create = AgentToolkitCreate(
                agent_id=agent_id,
                toolkit_id=toolkit_id,
                toolkit_type=toolkit.toolkit_type,
            )
            result = await self.agent_toolkit_repo.create(session, repo_create)
        match result:
            case Success(value):
                return Success(
                    AgentToolkitOutput.model_validate(value, from_attributes=True)
                )
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def detach_from_agent(
        self,
        agent_toolkit_id: str,
        *,
        agent_id: str,
        workspace_id: str,
    ) -> Result[
        None,
        AgentToolkitNotBelongToAgent | AgentNotBelongToWorkspace | ScopeNotFound,
    ]:
        """Unmount Toolkit from agent.

        :param agent_toolkit_id: AgentToolkit ID
        :param agent_id: Agent ID
        :param workspace_id: Workspace ID
        :return: Success or error
        """
        agent_error = await self._check_agent_workspace(agent_id, workspace_id)
        if agent_error is not None:
            return Failure(agent_error)

        async with self.session_manager() as session:
            agent_toolkit = await self.agent_toolkit_repo.get_by_id(
                session, agent_toolkit_id
            )
        if agent_toolkit is None:
            return Failure(ScopeNotFound(scope_id=agent_toolkit_id))
        if agent_toolkit.agent_id != agent_id:
            return Failure(
                AgentToolkitNotBelongToAgent(agent_toolkit_id=agent_toolkit_id)
            )

        async with self.session_manager() as session:
            await self.agent_toolkit_repo.delete_by_id(session, agent_toolkit_id)
        return Success(None)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _get_managed_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        for_update: bool,
    ) -> Result[Agent, AgentNotBelongToWorkspace | NotAdmin]:
        """Load an active Agent and verify Owner or explicit AgentAdmin authority."""
        agent = (
            await self.agent_repo.lock_by_id(session, agent_id)
            if for_update
            else await self.agent_repo.get_by_id(session, agent_id)
        )
        if (
            agent is None
            or agent.workspace_id != workspace_id
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
        ):
            return Failure(AgentNotBelongToWorkspace(agent_id=agent_id))
        if role is WorkspaceUserRole.OWNER:
            return Success(agent)
        if not await self.agent_admin_repo.is_admin(
            session,
            agent_id,
            workspace_user_id,
        ):
            return Failure(NotAdmin(agent_id=agent_id))
        return Success(agent)

    def _readiness(self, toolkit: ToolkitOutput) -> ToolkitReadiness:
        """Return the known persisted readiness state for management UI."""
        if not toolkit.enabled:
            return "disabled"
        if toolkit.authorization_state is not None:
            return "authorization_required"
        mcp_config = _resolve_mcp_config(
            toolkit.toolkit_type,
            toolkit.config,
            self.toolkit_registry,
        )
        if mcp_config is not None and mcp_config.auth_type == "oauth2":
            if (
                toolkit.oauth_connection is None
                or toolkit.oauth_connection.status
                is not MCPOAuthConnectionStatus.CONNECTED
            ):
                return "authorization_required"
        return "ready"

    async def _attach_oauth_connection(self, toolkit: ToolkitOutput) -> ToolkitOutput:
        """Attach redacted authorization state to one Toolkit output.

        :param toolkit: Toolkit output
        :return: Toolkit output with public authorization state
        """
        result = await self._attach_mcp_oauth_connection(toolkit)
        platform_credentials = self._platform_credentials(result)
        if platform_credentials is None:
            return result
        platform = await self.github_runtime.resolve()
        authorization_state = self.github_runtime.authorization_state(
            platform_credentials,
            effective_app_id=platform.app_id,
        )
        return result.model_copy(update={"authorization_state": authorization_state})

    async def _attach_oauth_connections(
        self, toolkits: list[ToolkitOutput]
    ) -> list[ToolkitOutput]:
        """Attach public authorization states using one Platform snapshot."""
        results = [
            await self._attach_mcp_oauth_connection(toolkit) for toolkit in toolkits
        ]
        platform_items = [
            (toolkit, self._platform_credentials(toolkit)) for toolkit in results
        ]
        if not any(credentials is not None for _, credentials in platform_items):
            return results
        platform = await self.github_runtime.resolve()
        return [
            toolkit.model_copy(
                update={
                    "authorization_state": self.github_runtime.authorization_state(
                        credentials,
                        effective_app_id=platform.app_id,
                    )
                }
            )
            if credentials is not None
            else toolkit
            for toolkit, credentials in platform_items
        ]

    async def _attach_mcp_oauth_connection(
        self,
        toolkit: ToolkitOutput,
    ) -> ToolkitOutput:
        """Attach an MCP OAuth connection summary when applicable."""
        mcp_config = _resolve_mcp_config(
            toolkit.toolkit_type, toolkit.config, self.toolkit_registry
        )
        if mcp_config is None or mcp_config.auth_type != "oauth2":
            return toolkit
        async with self.session_manager() as session:
            summary = await self.mcp_oauth_connection_repo.get_summary_by_toolkit_id(
                session, toolkit.id
            )
        return toolkit.model_copy(update={"oauth_connection": summary})

    async def _bind_platform_app_identity(
        self,
        credentials: dict[str, object] | None,
    ) -> dict[str, object] | None | InvalidCredentials:
        """Bind Platform GitHub credentials to the current server App identity."""
        if credentials is None or credentials.get("type") != "github_app_platform":
            return credentials
        platform = await self.github_runtime.resolve()
        if platform.app_id is None:
            return InvalidCredentials("Platform GitHub App is not configured.")
        return {**credentials, "app_id": platform.app_id}

    @staticmethod
    def _platform_credentials(
        toolkit: ToolkitOutput,
    ) -> GitHubSecretsAppPlatform | None:
        """Parse persisted Platform credentials for redacted projection."""
        if toolkit.toolkit_type != "github" or toolkit.credentials is None:
            return None
        credentials = _github_secrets_adapter.validate_json(toolkit.credentials)
        if isinstance(credentials, GitHubSecretsAppPlatform):
            return credentials
        return None

    def _validate_toolkit_type(self, toolkit_type: str) -> InvalidToolkitType | None:
        """Check whether toolkit type exists in toolkit_registry.

        :param toolkit_type: Tool type
        :return: Error or None
        """
        if toolkit_type not in self.toolkit_registry:
            return InvalidToolkitType(toolkit_type=toolkit_type)
        return None

    def _validate_config(
        self, toolkit_type: str, config: dict[str, object]
    ) -> InvalidConfig | None:
        """Validate config with Pydantic config model.

        :param toolkit_type: Tool type
        :param config: Config to validate
        :return: Error or None
        """
        provider = self.toolkit_registry.get(toolkit_type)
        if provider is None:
            return None  # Type error is handled by _validate_toolkit_type

        try:
            type(provider).validate_config(config)
        except ValidationError as e:
            return InvalidConfig(toolkit_type=toolkit_type, detail=str(e))
        return None

    def _validate_credentials(
        self,
        toolkit_type: str,
        credentials: dict[str, object] | None,
    ) -> InvalidConfig | None:
        """Validate credentials as McpSecrets when MCP toolkit.

        :param toolkit_type: Tool type
        :param credentials: Credentials to validate
        :return: Error or None
        """
        if credentials is None:
            return None
        try:
            tt = ToolkitType(toolkit_type)
        except ValueError:
            return None
        if tt == ToolkitType.MCP:
            try:
                _mcp_secrets_adapter.validate_python(credentials)
            except ValidationError as e:
                return InvalidConfig(toolkit_type=toolkit_type, detail=str(e))
        if tt == ToolkitType.GITHUB:
            try:
                _github_secrets_adapter.validate_python(credentials)
            except ValidationError as e:
                return InvalidConfig(toolkit_type=toolkit_type, detail=str(e))
        return None

    async def _check_agent_workspace(
        self, agent_id: str, workspace_id: str
    ) -> AgentNotBelongToWorkspace | None:
        """Check whether agent belongs to workspace.

        :param agent_id: Agent ID
        :param workspace_id: Workspace ID
        :return: Error or None
        """
        async with self.session_manager() as session:
            agent = await self.agent_repo.get_by_id(session, agent_id)
        if agent is None or agent.workspace_id != workspace_id:
            return AgentNotBelongToWorkspace(agent_id=agent_id)
        return None
