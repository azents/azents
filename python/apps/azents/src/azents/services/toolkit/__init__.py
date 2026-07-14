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
from azents.core.enums import ToolkitScopeType
from azents.core.github_credentials import GitHubSecrets
from azents.core.mcp_credentials import McpSecrets
from azents.core.tools import McpToolkitConfig, ToolkitProvider, ToolkitType
from azents.engine.tools.deps import get_toolkit_registry
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
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
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    toolkit_registry: Annotated[
        dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)
    ]

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

        cred_error = self._validate_credentials(create.toolkit_type, create.credentials)
        if cred_error is not None:
            return Failure(cred_error)

        # Validate credentials by provider (e.g. GitHub installation ownership)
        provider = self.toolkit_registry.get(create.toolkit_type)
        if provider is not None:
            async with self.session_manager() as session:
                cred_err_msg = await provider.validate_credentials(
                    session, user_id, create.credentials
                )
            if cred_err_msg is not None:
                return Failure(InvalidCredentials(cred_err_msg))

        # Use toolkit_type as default when slug is unspecified
        slug = create.slug if create.slug is not None else create.toolkit_type

        credentials_json: str | None = None
        if create.credentials is not None:
            credentials_json = json.dumps(create.credentials)

        repo_create = ToolkitCreate(
            workspace_id=create.workspace_id,
            toolkit_type=create.toolkit_type,
            slug=slug,
            name=create.name,
            description=create.description,
            config=create.config,
            prompt=create.prompt,
            credentials=credentials_json,
            enabled=create.enabled,
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
                case Failure(error):
                    return Failure(DuplicateSlug(slug=error.slug))
                case _:
                    assert_never(result)
        # A new Toolkit cannot have an OAuth connection before its create
        # transaction commits and the separate OAuth flow starts. Returning the
        # explicit disconnected projection avoids a nested post-write DB session
        # and keeps create failure atomicity unambiguous.
        return Success(output)

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
            toolkit = await self.toolkit_repo.get_by_id(session, toolkit_id)
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
            existing = await self.toolkit_repo.get_by_id(session, toolkit_id)
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

        if "credentials" in update and update["credentials"] is not None:
            cred_error = self._validate_credentials(
                existing.toolkit_type, update["credentials"]
            )
            if cred_error is not None:
                return Failure(cred_error)

        if "credentials" in update and update["credentials"] is not None:
            provider = self.toolkit_registry.get(existing.toolkit_type)
            if provider is not None:
                async with self.session_manager() as session:
                    cred_err_msg = await provider.validate_credentials(
                        session, user_id, update["credentials"]
                    )
                if cred_err_msg is not None:
                    return Failure(InvalidCredentials(cred_err_msg))

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
        if "credentials" in update:
            creds = update["credentials"]
            repo_update["credentials"] = (
                json.dumps(creds) if creds is not None else None
            )
        if "enabled" in update:
            repo_update["enabled"] = update["enabled"]

        # Delete existing credentials when auth_type changes
        if "config" in update and "credentials" not in update:
            old_auth = existing.config.get("auth_type") if existing.config else None
            new_auth = update["config"].get("auth_type") if update["config"] else None
            if old_auth != new_auth and new_auth is not None:
                repo_update["credentials"] = None

        # Resolve optional projection state before the durable write. A summary
        # read failure must not make an already committed update look failed.
        projected_config = update["config"] if "config" in update else existing.config
        oauth_snapshot = await self._attach_oauth_connection(
            ToolkitOutput.model_validate(existing, from_attributes=True).model_copy(
                update={"config": projected_config}
            )
        )
        async with self.session_manager() as session:
            result = await self.toolkit_repo.update_by_id(
                session, toolkit_id, repo_update
            )
        match result:
            case Success(value):
                output = ToolkitOutput.model_validate(value, from_attributes=True)
                return Success(
                    output.model_copy(
                        update={"oauth_connection": oauth_snapshot.oauth_connection}
                    )
                )
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
            existing = await self.toolkit_repo.get_by_id(session, toolkit_id)
        if existing is None:
            return Failure(NotFound(toolkit_id=toolkit_id))
        if existing.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(toolkit_id=toolkit_id))

        async with self.session_manager() as session:
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
            toolkit = await self.toolkit_repo.get_by_id(session, create.toolkit_id)
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
            toolkit = await self.toolkit_repo.get_by_id(session, toolkit_id)
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
            toolkit = await self.toolkit_repo.get_by_id(session, toolkit_id)
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
        | AgentNotBelongToWorkspace,
    ]:
        """Mount Toolkit on agent.

        :param agent_id: Agent ID
        :param toolkit_id: Toolkit ID
        :param workspace_id: Workspace ID
        :param user_id: Requesting user ID
        :return: Created AgentToolkit or error
        """
        agent_error = await self._check_agent_workspace(agent_id, workspace_id)
        if agent_error is not None:
            return Failure(agent_error)

        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_by_id(session, toolkit_id)
        if toolkit is None:
            return Failure(NotFound(toolkit_id=toolkit_id))
        if toolkit.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(toolkit_id=toolkit_id))

        # Check availability
        async with self.session_manager() as session:
            available = await self.toolkit_repo.list_available_for_workspace_user(
                session, workspace_id, user_id
            )
        available_ids = {t.id for t in available}
        if toolkit_id not in available_ids:
            return Failure(ToolkitNotAvailable(toolkit_id=toolkit_id))

        repo_create = AgentToolkitCreate(
            agent_id=agent_id,
            toolkit_id=toolkit_id,
            toolkit_type=toolkit.toolkit_type,
        )
        async with self.session_manager() as session:
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

    async def _attach_oauth_connection(self, toolkit: ToolkitOutput) -> ToolkitOutput:
        """Attach MCP OAuth connection summary to Toolkit output.

        :param toolkit: Toolkit output
        :return: Toolkit output with OAuth connection summary
        """
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

    async def _attach_oauth_connections(
        self, toolkits: list[ToolkitOutput]
    ) -> list[ToolkitOutput]:
        """Attach OAuth connection summaries to Toolkit outputs."""
        result: list[ToolkitOutput] = []
        for toolkit in toolkits:
            result.append(await self._attach_oauth_connection(toolkit))
        return result

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
