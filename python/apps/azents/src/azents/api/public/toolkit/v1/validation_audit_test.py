"""Toolkit validation/default and HTTP-error contracts at their narrow owning layer."""

import pytest
from azcommon.result import Failure, Result
from fastapi import HTTPException

from azents.api.public.toolkit.v1 import (
    attach_toolkit_to_agent,
    create_toolkit_config,
    detach_toolkit_from_agent,
)
from azents.api.public.toolkit.v1.data import (
    AgentToolkitAttachRequest,
    ToolkitConfigCreateRequest,
)
from azents.core.auth.deps import WorkspaceMember
from azents.core.auth.permissions import Permissions
from azents.core.enums import WorkspaceUserRole
from azents.core.toolkit_errors import (
    AgentToolkitNotFound,
    DuplicateAgentToolkit,
    NotFound,
)
from azents.core.toolkit_identifiers import (
    IdentifierValidationError,
    ResolvedToolkitIdentifiers,
    resolve_create_identifiers,
)
from azents.engine.tools.envvar import EnvVarToolkitProvider
from azents.engine.tools.mcp import McpToolkitProvider
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import (
    AgentNotBelongToWorkspace,
    AgentToolkitNotBelongToAgent,
    AgentToolkitOutput,
    InvalidConfig,
    InvalidCredentials,
    InvalidIdentifier,
    InvalidToolkitType,
    NotBelongToWorkspace,
    ToolkitCreateInput,
    ToolkitNotAvailable,
    ToolkitOutput,
)


class _ValidationService(ToolkitService):
    """Typed validation/error collaborator with no repository or provider I/O."""

    def __init__(self) -> None:
        self.toolkit_registry = {}
        self.create_calls: list[ToolkitCreateInput] = []

    async def create(
        self, create: ToolkitCreateInput, *, user_id: str
    ) -> Result[
        ToolkitOutput,
        InvalidToolkitType | InvalidConfig | InvalidIdentifier | InvalidCredentials,
    ]:
        self.create_calls.append(create)
        if create.toolkit_type == "mcp":
            identifiers = resolve_create_identifiers(
                toolkit_type="mcp",
                canonical_name=McpToolkitProvider.name,
                submitted_name=create.name,
                submitted_slug=create.slug,
            )
            assert isinstance(identifiers, IdentifierValidationError)
            return Failure(
                InvalidIdentifier(field=identifiers.field, detail=identifiers.detail)
            )
        error = self._validate_toolkit_type(create.toolkit_type)
        assert error is not None
        return Failure(error)

    async def detach_from_agent(
        self,
        agent_toolkit_id: str,
        *,
        agent_id: str,
        workspace_id: str,
    ) -> Result[
        None,
        AgentToolkitNotBelongToAgent | AgentNotBelongToWorkspace | AgentToolkitNotFound,
    ]:
        return Failure(AgentToolkitNotFound(agent_toolkit_id=agent_toolkit_id))

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
        return Failure(DuplicateAgentToolkit(agent_id=agent_id, toolkit_id=toolkit_id))


def _owner() -> WorkspaceMember:
    return WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="member-1",
        role=WorkspaceUserRole.OWNER,
        permissions={Permissions.TOOLKITS_READ, Permissions.TOOLKITS_WRITE},
        session_id="auth-session",
    )


def test_identifier_defaults_use_registered_provider_metadata() -> None:
    result = resolve_create_identifiers(
        toolkit_type="envvar",
        canonical_name=EnvVarToolkitProvider.name,
        submitted_name=None,
        submitted_slug=None,
    )
    assert result == ResolvedToolkitIdentifiers(
        name="Environment Variables", slug="environment_variables"
    )


def test_generic_mcp_non_latin_name_retains_name_and_uses_provider_slug() -> None:
    result = resolve_create_identifiers(
        toolkit_type="mcp",
        canonical_name=McpToolkitProvider.name,
        submitted_name="내부 검색",
        submitted_slug=None,
    )
    assert result == ResolvedToolkitIdentifiers(name="내부 검색", slug="mcp")


def test_generic_mcp_requires_an_explicit_name() -> None:
    result = resolve_create_identifiers(
        toolkit_type="mcp",
        canonical_name=McpToolkitProvider.name,
        submitted_name=None,
        submitted_slug=None,
    )
    assert isinstance(result, IdentifierValidationError)
    assert result.field == "name"
    assert result.detail == "Name is required for generic MCP Toolkits."


async def test_unknown_toolkit_type_maps_to_400_without_repository_io() -> None:
    service = _ValidationService()
    with pytest.raises(HTTPException) as raised:
        await create_toolkit_config(
            _owner(),
            service,
            request_body=ToolkitConfigCreateRequest(
                toolkit_type="unknown-provider",
                name="Unknown",
                config={},
                always_expose_tools=False,
            ),
        )
    assert raised.value.status_code == 400
    assert raised.value.detail == "Unknown toolkit type."
    assert len(service.create_calls) == 1


async def test_shell_creation_is_rejected_before_service_mutation() -> None:
    service = _ValidationService()
    with pytest.raises(HTTPException) as raised:
        await create_toolkit_config(
            _owner(),
            service,
            request_body=ToolkitConfigCreateRequest(
                toolkit_type="shell",
                name="Shell",
                config={},
                always_expose_tools=False,
            ),
        )
    assert raised.value.status_code == 400
    assert service.create_calls == []


async def test_nameless_generic_mcp_maps_to_name_field_422() -> None:
    with pytest.raises(HTTPException) as raised:
        await create_toolkit_config(
            _owner(),
            _ValidationService(),
            request_body=ToolkitConfigCreateRequest(
                toolkit_type="mcp",
                config={"server_url": "https://example.test/mcp", "auth_type": "none"},
                always_expose_tools=False,
            ),
        )
    assert raised.value.status_code == 422
    assert raised.value.detail == [
        {
            "type": "value_error",
            "loc": ["body", "name"],
            "msg": "Name is required for generic MCP Toolkits.",
            "input": None,
        }
    ]


async def test_missing_agent_attachment_maps_to_404() -> None:
    with pytest.raises(HTTPException) as raised:
        await detach_toolkit_from_agent(
            _owner(),
            _ValidationService(),
            agent_id="agent-1",
            agent_toolkit_id="missing-attachment",
        )
    assert raised.value.status_code == 404
    assert raised.value.detail == "Agent toolkit not found."


async def test_duplicate_agent_attachment_maps_to_409() -> None:
    with pytest.raises(HTTPException) as raised:
        await attach_toolkit_to_agent(
            _owner(),
            _ValidationService(),
            agent_id="agent-1",
            request_body=AgentToolkitAttachRequest(toolkit_id="toolkit-1"),
        )
    assert raised.value.status_code == 409
    assert raised.value.detail == "Agent already has this toolkit attached."
