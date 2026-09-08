"""Toolkit service."""

import dataclasses
import json
from typing import Annotated, Any, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from pydantic import TypeAdapter, ValidationError

from azents.core.github_credentials import GitHubSecrets, GitHubSecretsAppPlatform
from azents.core.mcp_credentials import McpSecrets
from azents.core.tools import McpToolkitConfig, ToolkitProvider, ToolkitType
from azents.engine.tools.deps import get_toolkit_registry
from azents.engine.tools.envvar import EnvVarToolkitSecrets
from azents.repos.toolkit.data import (
    DuplicateAgentToolkit,
    DuplicateScope,
    NotFound,
    ScopeNotFound,
    ToolkitConfig,
    ToolkitCreate,
    ToolkitUpdate,
)
from azents.repos.toolkit.data import DuplicateSlug as RepoDuplicateSlug
from azents.repos.toolkit_operations import ToolkitOperationsRepository
from azents.repos.toolkit_operations.data import (
    AgentToolkitMismatch,
    AgentWorkspaceMismatch,
    PlatformAuthorityRejected,
    PlatformToolkitAuthority,
    ScopeToolkitMismatch,
    ToolkitUnavailable,
    ToolkitWithOAuth,
    ToolkitWorkspaceMismatch,
)
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)

from .data import (
    AgentNotBelongToWorkspace,
    AgentToolkitListOutput,
    AgentToolkitNotBelongToAgent,
    AgentToolkitOutput,
    DuplicateSlug,
    InvalidConfig,
    InvalidCredentials,
    InvalidToolkitType,
    NotBelongToWorkspace,
    ScopeNotBelongToToolkit,
    ToolkitCreateInput,
    ToolkitListOutput,
    ToolkitNotAvailable,
    ToolkitOutput,
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


@dataclasses.dataclass(frozen=True)
class _PreparedCredentials:
    """Credentials normalized against one external Platform settings snapshot."""

    credentials: dict[str, object] | None
    platform: ResolvedPlatformGitHubApp | None


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


@dataclasses.dataclass
class ToolkitService:
    """Toolkit CRUD, Scope, and Agent attachment orchestration."""

    operations_repository: Annotated[
        ToolkitOperationsRepository,
        Depends(ToolkitOperationsRepository),
    ]
    toolkit_registry: Annotated[
        dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)
    ]
    github_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()]

    async def create(
        self, create: ToolkitCreateInput, *, user_id: str
    ) -> Result[
        ToolkitOutput,
        InvalidToolkitType | InvalidConfig | DuplicateSlug | InvalidCredentials,
    ]:
        """Create a Toolkit and its Workspace scope atomically."""
        type_error = self._validate_toolkit_type(create.toolkit_type)
        if type_error is not None:
            return Failure(type_error)
        config_error = self._validate_config(create.toolkit_type, create.config)
        if config_error is not None:
            return Failure(config_error)

        prepared = await self._prepare_credentials(create.credentials)
        if isinstance(prepared, InvalidCredentials):
            return Failure(prepared)
        credential_error = self._validate_credentials(
            create.toolkit_type,
            prepared.credentials,
        )
        if credential_error is not None:
            return Failure(credential_error)
        provider_error = await self._validate_provider_credentials(
            create.toolkit_type,
            prepared.credentials,
        )
        if provider_error is not None:
            return Failure(provider_error)

        slug = create.slug if create.slug is not None else create.toolkit_type
        credentials_json = (
            json.dumps(prepared.credentials)
            if prepared.credentials is not None
            else None
        )
        result = await self.operations_repository.create(
            ToolkitCreate(
                workspace_id=create.workspace_id,
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
            platform_authority=self._platform_authority(
                prepared,
                user_id=user_id,
            ),
        )
        match result:
            case Success(value):
                output = self._output_with_oauth(value)
                return Success(
                    self._attach_platform_authorization(output, prepared.platform)
                )
            case Failure(error):
                if isinstance(error, RepoDuplicateSlug):
                    return Failure(DuplicateSlug(slug=error.slug))
                return Failure(InvalidCredentials(error.detail))
            case _:
                assert_never(result)

    async def list_by_workspace(self, workspace_id: str) -> ToolkitListOutput:
        """Fetch all Toolkits in a Workspace."""
        values = await self.operations_repository.list_by_workspace(workspace_id)
        outputs = [self._output_with_oauth(value) for value in values]
        return ToolkitListOutput(items=await self._attach_oauth_connections(outputs))

    async def get_by_id(
        self, toolkit_id: str, *, workspace_id: str
    ) -> Result[ToolkitOutput, NotFound | NotBelongToWorkspace]:
        """Fetch one Toolkit after Workspace isolation validation."""
        result = await self.operations_repository.get_by_id(
            toolkit_id,
            workspace_id=workspace_id,
        )
        if isinstance(result, Failure):
            return Failure(self._map_toolkit_read_error(result.error))
        output = self._output_with_oauth(result.value)
        return Success(await self._attach_oauth_connection(output, attach_mcp=False))

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
        | InvalidCredentials,
    ]:
        """Update one Toolkit after external preparation and final revalidation."""
        existing_result = await self.operations_repository.load_update_context(
            toolkit_id,
            workspace_id=workspace_id,
        )
        if isinstance(existing_result, Failure):
            return Failure(self._map_toolkit_read_error(existing_result.error))
        existing = existing_result.value

        if "config" in update:
            config_error = self._validate_config(
                existing.toolkit_type,
                update["config"],
            )
            if config_error is not None:
                return Failure(config_error)

        normalized_credentials: dict[str, object] | None = None
        platform: ResolvedPlatformGitHubApp | None = None
        if "credentials" in update:
            update_credentials = update["credentials"]
            if update_credentials is not None:
                prepared = await self._prepare_credentials(update_credentials)
                if isinstance(prepared, InvalidCredentials):
                    return Failure(prepared)
                normalized_credentials = prepared.credentials
                platform = prepared.platform
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
                provider_error = await self._validate_provider_credentials(
                    existing.toolkit_type,
                    normalized_credentials,
                )
                if provider_error is not None:
                    return Failure(provider_error)
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

        repo_update = self._build_repo_update(
            update,
            existing=existing,
            normalized_credentials=normalized_credentials,
        )
        prepared_for_authority = _PreparedCredentials(
            credentials=normalized_credentials,
            platform=platform,
        )
        result = await self.operations_repository.update(
            toolkit_id,
            repo_update,
            workspace_id=workspace_id,
            expected_toolkit_type=existing.toolkit_type,
            platform_authority=self._platform_authority(
                prepared_for_authority,
                user_id=user_id,
            ),
        )
        match result:
            case Success(value):
                output = ToolkitOutput.model_validate(value, from_attributes=True)
                return Success(await self._attach_oauth_connection(output))
            case Failure(error):
                if isinstance(error, RepoDuplicateSlug):
                    return Failure(DuplicateSlug(slug=error.slug))
                if isinstance(error, PlatformAuthorityRejected):
                    return Failure(InvalidCredentials(error.detail))
                return Failure(self._map_toolkit_read_error(error))
            case _:
                assert_never(result)

    async def delete_by_id(
        self, toolkit_id: str, *, workspace_id: str
    ) -> Result[None, NotFound | NotBelongToWorkspace]:
        """Delete one Toolkit after final Workspace validation."""
        result = await self.operations_repository.delete(
            toolkit_id,
            workspace_id=workspace_id,
        )
        if isinstance(result, Failure):
            return Failure(self._map_toolkit_read_error(result.error))
        return Success(None)

    async def create_scope(
        self, create: ToolkitScopeCreateInput, *, workspace_id: str
    ) -> Result[ToolkitScopeOutput, NotFound | NotBelongToWorkspace | DuplicateScope]:
        """Create one Workspace Scope with current Toolkit authority."""
        result = await self.operations_repository.create_scope(
            toolkit_id=create.toolkit_id,
            workspace_id=workspace_id,
        )
        if isinstance(result, Success):
            return Success(
                ToolkitScopeOutput.model_validate(result.value, from_attributes=True)
            )
        if isinstance(result.error, (NotFound, ToolkitWorkspaceMismatch)):
            return Failure(self._map_toolkit_read_error(result.error))
        return Failure(result.error)

    async def list_scopes(
        self, toolkit_id: str, *, workspace_id: str
    ) -> Result[ToolkitScopeListOutput, NotFound | NotBelongToWorkspace]:
        """Fetch Scopes for one Workspace Toolkit."""
        result = await self.operations_repository.list_scopes(
            toolkit_id,
            workspace_id=workspace_id,
        )
        if isinstance(result, Failure):
            return Failure(self._map_toolkit_read_error(result.error))
        return Success(
            ToolkitScopeListOutput(
                items=[
                    ToolkitScopeOutput.model_validate(scope, from_attributes=True)
                    for scope in result.value
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
        """Delete one Scope after final Toolkit and Scope identity validation."""
        result = await self.operations_repository.delete_scope(
            scope_id,
            toolkit_id=toolkit_id,
            workspace_id=workspace_id,
        )
        if isinstance(result, Success):
            return Success(None)
        error = result.error
        if isinstance(error, (NotFound, ToolkitWorkspaceMismatch)):
            return Failure(self._map_toolkit_read_error(error))
        if isinstance(error, ScopeToolkitMismatch):
            return Failure(ScopeNotBelongToToolkit(scope_id=error.scope_id))
        return Failure(error)

    async def list_available(
        self, workspace_id: str, user_id: str
    ) -> ToolkitListOutput:
        """Fetch Toolkits available to one Workspace user."""
        values = await self.operations_repository.list_available(workspace_id, user_id)
        outputs = [self._output_with_oauth(value) for value in values]
        return ToolkitListOutput(items=await self._attach_oauth_connections(outputs))

    async def list_agent_toolkits(
        self, agent_id: str, *, workspace_id: str
    ) -> Result[AgentToolkitListOutput, AgentNotBelongToWorkspace]:
        """Fetch Toolkit attachments for one Workspace Agent."""
        result = await self.operations_repository.list_agent_toolkits(
            agent_id,
            workspace_id=workspace_id,
        )
        if isinstance(result, Failure):
            return Failure(AgentNotBelongToWorkspace(agent_id=agent_id))
        return Success(
            AgentToolkitListOutput(
                items=[
                    AgentToolkitOutput.model_validate(item, from_attributes=True)
                    for item in result.value
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
        | AgentNotBelongToWorkspace,
    ]:
        """Attach one currently available Toolkit to an Agent atomically."""
        result = await self.operations_repository.attach_to_agent(
            agent_id,
            toolkit_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if isinstance(result, Success):
            return Success(
                AgentToolkitOutput.model_validate(result.value, from_attributes=True)
            )
        error = result.error
        if isinstance(error, AgentWorkspaceMismatch):
            return Failure(AgentNotBelongToWorkspace(agent_id=agent_id))
        if isinstance(error, ToolkitWorkspaceMismatch):
            return Failure(NotBelongToWorkspace(toolkit_id=toolkit_id))
        if isinstance(error, ToolkitUnavailable):
            return Failure(ToolkitNotAvailable(toolkit_id=toolkit_id))
        return Failure(error)

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
        """Detach one Toolkit after final Agent and attachment validation."""
        result = await self.operations_repository.detach_from_agent(
            agent_toolkit_id,
            agent_id=agent_id,
            workspace_id=workspace_id,
        )
        if isinstance(result, Success):
            return Success(None)
        error = result.error
        if isinstance(error, AgentWorkspaceMismatch):
            return Failure(AgentNotBelongToWorkspace(agent_id=agent_id))
        if isinstance(error, AgentToolkitMismatch):
            return Failure(
                AgentToolkitNotBelongToAgent(agent_toolkit_id=agent_toolkit_id)
            )
        return Failure(error)

    async def _attach_oauth_connection(
        self,
        toolkit: ToolkitOutput,
        *,
        attach_mcp: bool = True,
    ) -> ToolkitOutput:
        """Attach current MCP and Platform authorization projections."""
        result = (
            await self._attach_mcp_oauth_connection(toolkit) if attach_mcp else toolkit
        )
        platform_credentials = self._platform_credentials(result)
        if platform_credentials is None:
            return result
        platform = await self.github_runtime.resolve()
        return self._attach_platform_authorization(result, platform)

    async def _attach_oauth_connections(
        self, toolkits: list[ToolkitOutput]
    ) -> list[ToolkitOutput]:
        """Attach public Platform authorization states using one snapshot."""
        platform_items = [
            (toolkit, self._platform_credentials(toolkit)) for toolkit in toolkits
        ]
        if not any(credentials is not None for _, credentials in platform_items):
            return toolkits
        platform = await self.github_runtime.resolve()
        return [
            self._attach_platform_authorization(toolkit, platform)
            if credentials is not None
            else toolkit
            for toolkit, credentials in platform_items
        ]

    async def _attach_mcp_oauth_connection(
        self,
        toolkit: ToolkitOutput,
    ) -> ToolkitOutput:
        """Attach an MCP OAuth summary through a completed repository operation."""
        mcp_config = _resolve_mcp_config(
            toolkit.toolkit_type,
            toolkit.config,
            self.toolkit_registry,
        )
        if mcp_config is None or mcp_config.auth_type != "oauth2":
            return toolkit
        summary = await self.operations_repository.get_oauth_summary(toolkit.id)
        return toolkit.model_copy(update={"oauth_connection": summary})

    async def _prepare_credentials(
        self,
        credentials: dict[str, object] | None,
    ) -> _PreparedCredentials | InvalidCredentials:
        """Bind Platform credentials to one external settings snapshot."""
        if credentials is None or credentials.get("type") != "github_app_platform":
            return _PreparedCredentials(credentials=credentials, platform=None)
        platform = await self.github_runtime.resolve()
        if platform.app_id is None:
            return InvalidCredentials("Platform GitHub App is not configured.")
        return _PreparedCredentials(
            credentials={**credentials, "app_id": platform.app_id},
            platform=platform,
        )

    def _platform_authority(
        self,
        prepared: _PreparedCredentials,
        *,
        user_id: str,
    ) -> PlatformToolkitAuthority | None:
        """Build final DB revalidation input for Platform credentials."""
        if prepared.credentials is None or prepared.platform is None:
            return None
        credentials = _github_secrets_adapter.validate_python(prepared.credentials)
        if not isinstance(credentials, GitHubSecretsAppPlatform):
            return None
        return PlatformToolkitAuthority(
            app_id=credentials.app_id,
            app_id_source=prepared.platform.app_id_source,
            user_id=user_id,
            installation_ids=frozenset(
                int(installation.installation_id)
                for installation in credentials.installations
            ),
        )

    @staticmethod
    def _attach_platform_authorization(
        toolkit: ToolkitOutput,
        platform: ResolvedPlatformGitHubApp | None,
    ) -> ToolkitOutput:
        """Attach redacted Platform reconnect state from a resolved snapshot."""
        if platform is None:
            return toolkit
        credentials = ToolkitService._platform_credentials(toolkit)
        if credentials is None:
            return toolkit
        authorization_state = PlatformGitHubAppRuntimeService.authorization_state(
            credentials,
            effective_app_id=platform.app_id,
        )
        return toolkit.model_copy(update={"authorization_state": authorization_state})

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

    @staticmethod
    def _map_toolkit_read_error(
        error: NotFound | ToolkitWorkspaceMismatch,
    ) -> NotFound | NotBelongToWorkspace:
        """Map repository ownership errors to the established service contract."""
        if isinstance(error, NotFound):
            return error
        return NotBelongToWorkspace(toolkit_id=error.toolkit_id)

    def _output_with_oauth(self, value: ToolkitWithOAuth) -> ToolkitOutput:
        """Project a detached Toolkit and applicable MCP OAuth summary."""
        output = ToolkitOutput.model_validate(value.toolkit, from_attributes=True)
        mcp_config = _resolve_mcp_config(
            output.toolkit_type,
            output.config,
            self.toolkit_registry,
        )
        if mcp_config is None or mcp_config.auth_type != "oauth2":
            return output
        return output.model_copy(update={"oauth_connection": value.oauth_connection})

    @staticmethod
    def _build_repo_update(
        update: ToolkitUpdateInput,
        *,
        existing: ToolkitConfig,
        normalized_credentials: dict[str, object] | None,
    ) -> ToolkitUpdate:
        """Convert the service patch to the encrypted repository patch shape."""
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

        if "config" in update and "credentials" not in update:
            old_auth = existing.config.get("auth_type") if existing.config else None
            new_auth = update["config"].get("auth_type") if update["config"] else None
            if old_auth != new_auth and new_auth is not None:
                repo_update["credentials"] = None
        return repo_update

    def _validate_toolkit_type(self, toolkit_type: str) -> InvalidToolkitType | None:
        """Check whether the Toolkit type exists in the registry."""
        if toolkit_type not in self.toolkit_registry:
            return InvalidToolkitType(toolkit_type=toolkit_type)
        return None

    def _validate_config(
        self, toolkit_type: str, config: dict[str, object]
    ) -> InvalidConfig | None:
        """Validate config with the registered provider model."""
        provider = self.toolkit_registry.get(toolkit_type)
        if provider is None:
            return None
        try:
            type(provider).validate_config(config)
        except ValidationError as error:
            return InvalidConfig(toolkit_type=toolkit_type, detail=str(error))
        return None

    def _validate_credentials(
        self,
        toolkit_type: str,
        credentials: dict[str, object] | None,
    ) -> InvalidConfig | None:
        """Validate common MCP and GitHub credential shapes."""
        if credentials is None:
            return None
        try:
            typed_toolkit = ToolkitType(toolkit_type)
        except ValueError:
            return None
        if typed_toolkit == ToolkitType.MCP:
            try:
                _mcp_secrets_adapter.validate_python(credentials)
            except ValidationError as error:
                return InvalidConfig(toolkit_type=toolkit_type, detail=str(error))
        if typed_toolkit == ToolkitType.GITHUB:
            try:
                _github_secrets_adapter.validate_python(credentials)
            except ValidationError as error:
                return InvalidConfig(toolkit_type=toolkit_type, detail=str(error))
        return None

    async def _validate_provider_credentials(
        self,
        toolkit_type: str,
        credentials: dict[str, object] | None,
    ) -> InvalidCredentials | None:
        """Run provider validation with no database transaction or session alias."""
        provider = self.toolkit_registry.get(toolkit_type)
        if provider is None:
            return None
        error = await provider.validate_credentials(credentials)
        return InvalidCredentials(error) if error is not None else None
