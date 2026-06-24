"""Public API Toolkit E2E test.

Toolkit CRUD, Scope t, Agent t/t t verifyt.
"""

from typing import Any, cast

import azentsadminclient
import azentspublicclient
import pytest
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.invitation_v1_api import InvitationV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.api.workspace_v1_api import (
    WorkspaceV1Api as PublicWorkspaceV1Api,
)
from azentspublicclient.exceptions import ApiException
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)
from azentspublicclient.models.agent_toolkit_attach_request import (
    AgentToolkitAttachRequest,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_invitation_request import (
    CreateInvitationRequest,
)
from azentspublicclient.models.create_workspace_request import (
    CreateWorkspaceRequest as PublicCreateWorkspaceRequest,
)
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from azentspublicclient.models.toolkit_config_update_request import (
    ToolkitConfigUpdateRequest,
)

from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
)

# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def _setup_workspace(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> tuple[str, str, str, AgentModelSelectionInput]:
    """workspace + LLM Integration create.

    :return: (owner_token, handle, integration_id, model_selection) t
    """
    uniq = unique()
    owner_token, _, _ = authenticate_user(public_api_client, admin_api_client)

    ws_api = PublicWorkspaceV1Api(public_api_client)
    handle = f"ws-tk-{uniq}"
    ws_api.workspace_v1_create_workspace(
        PublicCreateWorkspaceRequest(
            workspace_name=f"Toolkit WS {uniq}",
            workspace_handle=handle,
            owner_name=f"Owner {uniq}",
        ),
        _headers={"Authorization": f"Bearer {owner_token}"},
    )

    int_api = LLMProviderIntegrationV1Api(public_api_client)
    integration = int_api.llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-test-key")),
        ),
        _headers={"Authorization": f"Bearer {owner_token}"},
    )
    model_selection = model_selection_from_first_candidate(
        _api_host(public_api_client),
        owner_token,
        handle,
        integration.id,
    )

    return owner_token, handle, integration.id, model_selection


def _api_host(public_api_client: azentspublicclient.ApiClient) -> str:
    """Generated client t API host stringt t."""
    configuration = cast(Any, public_api_client).configuration
    return str(configuration.host)


def _add_member(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    *,
    owner_token: str,
    handle: str,
) -> str:
    """workspacet Membert invitationt access_tokent return."""
    uniq = unique()
    member_token, _, _ = authenticate_user(
        public_api_client, admin_api_client, email=f"member-{uniq}@example.com"
    )
    inv_api = InvitationV1Api(public_api_client)
    invitation = inv_api.invitation_v1_create_invitation(
        handle,
        CreateInvitationRequest(email=f"member-{uniq}@example.com"),
        _headers={"Authorization": f"Bearer {owner_token}"},
    )
    # tautht t token t (invitation emailt t t create)
    _, member_email = invitation.id, f"member-{uniq}@example.com"
    member_token, _, _ = authenticate_user(
        public_api_client, admin_api_client, email=member_email
    )
    inv_api.invitation_v1_accept_invitation(
        invitation.id,
        _headers={"Authorization": f"Bearer {member_token}"},
    )
    return member_token


def _create_toolkit(
    public_api_client: azentspublicclient.ApiClient,
    *,
    token: str,
    handle: str,
    name: str | None = None,
    enabled: bool = True,
) -> str:
    """Toolkitt createt IDt return."""
    api = ToolkitV1Api(public_api_client)
    uniq = unique()
    toolkit = api.toolkit_v1_create_toolkit_config(
        handle=handle,
        toolkit_config_create_request=ToolkitConfigCreateRequest(
            toolkit_type="mcp",
            slug=f"mcp_{uniq}",
            name=name or f"MCP Toolkit {uniq}",
            config={
                "server_url": "https://example.com/mcp",
                "auth_type": "none",
                "timeout": 30.0,
            },
            enabled=enabled,
        ),
        _headers={"Authorization": f"Bearer {token}"},
    )
    return toolkit.id


def _create_agent(
    public_api_client: azentspublicclient.ApiClient,
    *,
    token: str,
    handle: str,
    integration_id: str,
    model_selection: AgentModelSelectionInput,
) -> str:
    """Agentt createt IDt return."""
    api = AgentV1Api(public_api_client)
    uniq = unique()
    agent = api.agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"Agent {uniq}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
        ),
        _headers={"Authorization": f"Bearer {token}"},
    )
    return agent.id


# ---------------------------------------------------------------------------
# Toolkit CRUD (Manager/Owner)
# ---------------------------------------------------------------------------


class TestToolkitCrud:
    """Toolkit CRUD default t."""

    def test_create_and_get_toolkit(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Toolkit create t fetcht fieldt t."""
        owner_token, handle, _, _ = _setup_workspace(
            public_api_client, admin_api_client
        )
        api = ToolkitV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {owner_token}"}

        created = api.toolkit_v1_create_toolkit_config(
            handle=handle,
            toolkit_config_create_request=ToolkitConfigCreateRequest(
                toolkit_type="mcp",
                name="My MCP Toolkit",
                description="test toolkit",
                config={
                    "server_url": "https://example.com/mcp",
                    "auth_type": "none",
                    "timeout": 30.0,
                },
                enabled=True,
            ),
            _headers=headers,
        )

        assert created.id is not None
        assert created.toolkit_type == "mcp"
        assert created.name == "My MCP Toolkit"
        assert created.description == "test toolkit"
        assert created.enabled is True
        assert created.config["server_url"] == "https://example.com/mcp"
        assert created.config["auth_type"] == "none"

        fetched = api.toolkit_v1_get_toolkit_config(
            handle=handle, toolkit_config_id=created.id, _headers=headers
        )
        assert fetched.id == created.id
        assert fetched.name == "My MCP Toolkit"

    def test_list_toolkits(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Toolkit t t create t list fetch t t t returnt."""
        owner_token, handle, _, _ = _setup_workspace(
            public_api_client, admin_api_client
        )
        headers = {"Authorization": f"Bearer {owner_token}"}

        _create_toolkit(
            public_api_client, token=owner_token, handle=handle, name="Toolkit A"
        )
        _create_toolkit(
            public_api_client, token=owner_token, handle=handle, name="Toolkit B"
        )

        api = ToolkitV1Api(public_api_client)
        result = api.toolkit_v1_list_toolkit_configs(handle=handle, _headers=headers)

        assert len(result.items) == 2
        names = {t.name for t in result.items}
        assert "Toolkit A" in names
        assert "Toolkit B" in names

    def test_update_toolkit(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Toolkit t configt updatet t t."""
        owner_token, handle, _, _ = _setup_workspace(
            public_api_client, admin_api_client
        )
        api = ToolkitV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {owner_token}"}

        toolkit_id = _create_toolkit(
            public_api_client, token=owner_token, handle=handle, name="Original"
        )

        updated = api.toolkit_v1_update_toolkit_config(
            handle=handle,
            toolkit_config_id=toolkit_id,
            toolkit_config_update_request=ToolkitConfigUpdateRequest(
                name="Updated",
                config={
                    "server_url": "https://updated.com/mcp",
                    "auth_type": "none",
                    "timeout": 60.0,
                },
            ),
            _headers=headers,
        )

        assert updated.name == "Updated"
        assert updated.config["server_url"] == "https://updated.com/mcp"
        assert updated.config["timeout"] == 60.0

    def test_delete_toolkit(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Toolkit delete t fetch t 404t returnt."""
        owner_token, handle, _, _ = _setup_workspace(
            public_api_client, admin_api_client
        )
        api = ToolkitV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {owner_token}"}

        toolkit_id = _create_toolkit(
            public_api_client, token=owner_token, handle=handle
        )
        api.toolkit_v1_delete_toolkit_config(
            handle=handle, toolkit_config_id=toolkit_id, _headers=headers
        )

        with pytest.raises(ApiException) as exc_info:
            api.toolkit_v1_get_toolkit_config(
                handle=handle, toolkit_config_id=toolkit_id, _headers=headers
            )
        assert exc_info.value.status == 404  # pyright: ignore[reportUnknownMemberType]

    def test_invalid_toolkit_type_returns_400(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """existst t toolkit_typet create t 400t returnt."""
        owner_token, handle, _, _ = _setup_workspace(
            public_api_client, admin_api_client
        )
        api = ToolkitV1Api(public_api_client)

        with pytest.raises(ApiException) as exc_info:
            api.toolkit_v1_create_toolkit_config(
                handle=handle,
                toolkit_config_create_request=ToolkitConfigCreateRequest(
                    toolkit_type="nonexistent_tool",
                    name="Bad Toolkit",
                    config={},
                ),
                _headers={"Authorization": f"Bearer {owner_token}"},
            )
        assert exc_info.value.status == 400  # pyright: ignore[reportUnknownMemberType]

    def test_shell_toolkit_creation_blocked(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Shell toolkit config create t 400t returnt."""
        owner_token, handle, _, _ = _setup_workspace(
            public_api_client, admin_api_client
        )
        api = ToolkitV1Api(public_api_client)

        with pytest.raises(ApiException) as exc_info:
            api.toolkit_v1_create_toolkit_config(
                handle=handle,
                toolkit_config_create_request=ToolkitConfigCreateRequest(
                    toolkit_type="shell",
                    name="Shell Toolkit",
                    config={"allowed_domains": [], "denied_domains": []},
                ),
                _headers={"Authorization": f"Bearer {owner_token}"},
            )
        assert exc_info.value.status == 400  # pyright: ignore[reportUnknownMemberType]

    def test_member_cannot_create_toolkit(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Member permissiont Toolkit create t 403t returnt."""
        owner_token, handle, _, _ = _setup_workspace(
            public_api_client, admin_api_client
        )
        member_token = _add_member(
            public_api_client,
            admin_api_client,
            owner_token=owner_token,
            handle=handle,
        )
        api = ToolkitV1Api(public_api_client)

        with pytest.raises(ApiException) as exc_info:
            api.toolkit_v1_create_toolkit_config(
                handle=handle,
                toolkit_config_create_request=ToolkitConfigCreateRequest(
                    toolkit_type="mcp",
                    name="Member Toolkit",
                    config={
                        "server_url": "https://example.com/mcp",
                        "auth_type": "none",
                        "timeout": 30.0,
                    },
                ),
                _headers={"Authorization": f"Bearer {member_token}"},
            )
        assert exc_info.value.status == 403  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Scope t
# ---------------------------------------------------------------------------


class TestToolkitScope:
    """Toolkit Scope t t."""

    def test_auto_created_workspace_scope(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Toolkit create t Workspace Scopet t createt."""
        owner_token, handle, _, _ = _setup_workspace(
            public_api_client, admin_api_client
        )
        api = ToolkitV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {owner_token}"}

        toolkit_id = _create_toolkit(
            public_api_client, token=owner_token, handle=handle
        )

        # workspace_idt toolkit responset fetch
        toolkit = api.toolkit_v1_get_toolkit_config(
            handle=handle, toolkit_config_id=toolkit_id, _headers=headers
        )
        workspace_id = toolkit.workspace_id

        # Toolkit create t workspace scopet t createt
        scopes = api.toolkit_v1_list_toolkit_scopes(
            handle=handle, toolkit_config_id=toolkit_id, _headers=headers
        )
        assert len(scopes.items) == 1
        assert scopes.items[0].scope_type == "workspace"
        assert scopes.items[0].scope_id == workspace_id

    def test_duplicate_scope_returns_409(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t createt Workspace Scopet t create t 409t returnt."""
        owner_token, handle, _, _ = _setup_workspace(
            public_api_client, admin_api_client
        )
        api = ToolkitV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {owner_token}"}

        toolkit_id = _create_toolkit(
            public_api_client, token=owner_token, handle=handle
        )

        # Workspace scopet t createt, t scopet t t 409
        with pytest.raises(ApiException) as exc_info:
            api.toolkit_v1_create_toolkit_scope(
                handle=handle,
                toolkit_config_id=toolkit_id,
                _headers=headers,
            )
        assert exc_info.value.status == 409  # pyright: ignore[reportUnknownMemberType]

    def test_delete_scope(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Scope delete t listt t."""
        owner_token, handle, _, _ = _setup_workspace(
            public_api_client, admin_api_client
        )
        api = ToolkitV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {owner_token}"}

        toolkit_id = _create_toolkit(
            public_api_client, token=owner_token, handle=handle
        )

        # t createt workspace scopet t delete
        scopes = api.toolkit_v1_list_toolkit_scopes(
            handle=handle, toolkit_config_id=toolkit_id, _headers=headers
        )
        assert len(scopes.items) == 1
        auto_scope = scopes.items[0]

        api.toolkit_v1_delete_toolkit_scope(
            handle=handle,
            toolkit_config_id=toolkit_id,
            scope_id=auto_scope.id,
            _headers=headers,
        )

        scopes_after = api.toolkit_v1_list_toolkit_scopes(
            handle=handle, toolkit_config_id=toolkit_id, _headers=headers
        )
        assert len(scopes_after.items) == 0


# ---------------------------------------------------------------------------
# t Toolkit + Agent t
# ---------------------------------------------------------------------------


class TestToolkitAvailableAndAttach:
    """t Toolkit fetch + Agent t t."""

    def test_member_sees_workspace_scoped_toolkit(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Workspace t Toolkitt t membert t t."""
        owner_token, handle, _, _ = _setup_workspace(
            public_api_client, admin_api_client
        )
        member_token = _add_member(
            public_api_client,
            admin_api_client,
            owner_token=owner_token,
            handle=handle,
        )
        api = ToolkitV1Api(public_api_client)

        toolkit_id = _create_toolkit(
            public_api_client, token=owner_token, handle=handle, name="WS Toolkit"
        )

        # Workspace scopet t createt t t t

        # membert t list fetch
        available = api.toolkit_v1_list_available_toolkit_configs(
            handle=handle,
            _headers={"Authorization": f"Bearer {member_token}"},
        )
        assert any(t.id == toolkit_id for t in available.items)

    def test_disabled_toolkit_not_available(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """inactivet Toolkitt t listt t t."""
        owner_token, handle, _, _ = _setup_workspace(
            public_api_client, admin_api_client
        )
        api = ToolkitV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {owner_token}"}

        toolkit_id = _create_toolkit(
            public_api_client,
            token=owner_token,
            handle=handle,
            name="Disabled Toolkit",
            enabled=False,
        )

        # Workspace scopet t createt t t t

        available = api.toolkit_v1_list_available_toolkit_configs(
            handle=handle, _headers=headers
        )
        assert not any(t.id == toolkit_id for t in available.items)

    def test_attach_and_detach_toolkit(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Agentt Toolkitt t t t t."""
        owner_token, handle, integration_id, model_selection = _setup_workspace(
            public_api_client, admin_api_client
        )
        api = ToolkitV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {owner_token}"}

        toolkit_id = _create_toolkit(
            public_api_client, token=owner_token, handle=handle
        )

        # Workspace scopet t createt t t t

        agent_id = _create_agent(
            public_api_client,
            token=owner_token,
            handle=handle,
            integration_id=integration_id,
            model_selection=model_selection,
        )

        # t
        attached = api.toolkit_v1_attach_toolkit_to_agent(
            handle=handle,
            agent_id=agent_id,
            agent_toolkit_attach_request=AgentToolkitAttachRequest(
                toolkit_id=toolkit_id
            ),
            _headers=headers,
        )
        assert attached.toolkit_id == toolkit_id
        assert attached.toolkit_type == "mcp"

        # list check
        agent_toolkits = api.toolkit_v1_list_agent_toolkits(
            handle=handle, agent_id=agent_id, _headers=headers
        )
        assert len(agent_toolkits.items) == 1

        # t
        api.toolkit_v1_detach_toolkit_from_agent(
            handle=handle,
            agent_id=agent_id,
            agent_toolkit_id=attached.id,
            _headers=headers,
        )

        agent_toolkits_after = api.toolkit_v1_list_agent_toolkits(
            handle=handle, agent_id=agent_id, _headers=headers
        )
        assert len(agent_toolkits_after.items) == 0

    def test_duplicate_toolkit_attach_returns_409(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t Toolkitt Agentt t t t 409t returnt."""
        owner_token, handle, integration_id, model_selection = _setup_workspace(
            public_api_client, admin_api_client
        )
        api = ToolkitV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {owner_token}"}

        toolkit_id = _create_toolkit(
            public_api_client, token=owner_token, handle=handle, name="MCP 1"
        )

        agent_id = _create_agent(
            public_api_client,
            token=owner_token,
            handle=handle,
            integration_id=integration_id,
            model_selection=model_selection,
        )

        # t t t success
        api.toolkit_v1_attach_toolkit_to_agent(
            handle=handle,
            agent_id=agent_id,
            agent_toolkit_attach_request=AgentToolkitAttachRequest(
                toolkit_id=toolkit_id
            ),
            _headers=headers,
        )

        # t Toolkit t → 409
        with pytest.raises(ApiException) as exc_info:
            api.toolkit_v1_attach_toolkit_to_agent(
                handle=handle,
                agent_id=agent_id,
                agent_toolkit_attach_request=AgentToolkitAttachRequest(
                    toolkit_id=toolkit_id
                ),
                _headers=headers,
            )
        assert exc_info.value.status == 409  # pyright: ignore[reportUnknownMemberType]

    def test_unavailable_toolkit_returns_403(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Scope t Toolkitt t t t 403t returnt."""
        owner_token, handle, integration_id, model_selection = _setup_workspace(
            public_api_client, admin_api_client
        )
        api = ToolkitV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {owner_token}"}

        toolkit_id = _create_toolkit(
            public_api_client, token=owner_token, handle=handle
        )

        # t createt workspace scopet deletet scope t statet t
        scopes = api.toolkit_v1_list_toolkit_scopes(
            handle=handle, toolkit_config_id=toolkit_id, _headers=headers
        )
        for s in scopes.items:
            api.toolkit_v1_delete_toolkit_scope(
                handle=handle,
                toolkit_config_id=toolkit_id,
                scope_id=s.id,
                _headers=headers,
            )

        agent_id = _create_agent(
            public_api_client,
            token=owner_token,
            handle=handle,
            integration_id=integration_id,
            model_selection=model_selection,
        )

        with pytest.raises(ApiException) as exc_info:
            api.toolkit_v1_attach_toolkit_to_agent(
                handle=handle,
                agent_id=agent_id,
                agent_toolkit_attach_request=AgentToolkitAttachRequest(
                    toolkit_id=toolkit_id
                ),
                _headers=headers,
            )
        assert exc_info.value.status == 403  # pyright: ignore[reportUnknownMemberType]
