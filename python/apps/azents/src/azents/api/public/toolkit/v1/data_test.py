import datetime

from pydantic import TypeAdapter

from azents.api.public.toolkit.v1.data import (
    AgentToolkitConfigCreateRequest,
    AgentToolkitConfigUpdateRequest,
    ToolkitConfigCreateRequest,
    ToolkitConfigResponse,
    ToolkitConfigUpdateRequest,
)
from azents.core.github_user_oauth import (
    GitHubUserConnectionStatus,
    GitHubUserConnectionSummary,
)
from azents.services.toolkit.data import ToolkitOutput


def test_toolkit_config_create_request_accepts_underscore_slug() -> None:
    request = ToolkitConfigCreateRequest(
        toolkit_type="kubernetes",
        slug="home_kubernetes",
        name="Home Kubernetes",
        config={},
    )

    assert request.slug == "home_kubernetes"
    assert request.always_expose_tools is False


def test_toolkit_config_create_request_accepts_omitted_identifiers() -> None:
    request = ToolkitConfigCreateRequest(
        toolkit_type="kubernetes",
        config={},
    )

    assert request.slug is None
    assert request.name is None


def test_toolkit_config_create_request_defers_slug_normalization() -> None:
    request = ToolkitConfigCreateRequest(
        toolkit_type="kubernetes",
        slug="Home-Kubernetes",
        name="Home Kubernetes",
        config={},
    )

    assert request.slug == "Home-Kubernetes"


def test_toolkit_config_update_request_accepts_underscore_slug() -> None:
    adapter: TypeAdapter[ToolkitConfigUpdateRequest] = TypeAdapter(
        ToolkitConfigUpdateRequest
    )

    request = adapter.validate_python({"slug": "home_kubernetes"})

    assert request.get("slug") == "home_kubernetes"


def test_toolkit_config_update_request_accepts_always_expose_tools() -> None:
    adapter: TypeAdapter[ToolkitConfigUpdateRequest] = TypeAdapter(
        ToolkitConfigUpdateRequest
    )

    request = adapter.validate_python({"always_expose_tools": True})

    assert request.get("always_expose_tools") is True


def test_toolkit_config_update_request_accepts_blank_and_unormalized_slug() -> None:
    adapter: TypeAdapter[ToolkitConfigUpdateRequest] = TypeAdapter(
        ToolkitConfigUpdateRequest
    )

    assert adapter.validate_python({"slug": ""})["slug"] == ""
    assert (
        adapter.validate_python({"slug": "Home-Kubernetes"})["slug"]
        == "Home-Kubernetes"
    )


def test_toolkit_config_response_redacts_owner_and_credentials() -> None:
    """Expose credential presence without returning ownership or secret fields."""
    now = datetime.datetime.now(datetime.UTC)
    toolkit = ToolkitOutput(
        id="toolkit-1",
        workspace_id="workspace-1",
        owner_agent_id="agent-1",
        toolkit_type="mcp",
        slug="private_mcp",
        name="Private MCP",
        config={"server_url": "https://mcp.test", "auth_type": "none"},
        credentials='{"type":"bearer","token":"secret"}',
        enabled=True,
        always_expose_tools=False,
        revision=1,
        created_at=now,
        updated_at=now,
    )

    response = ToolkitConfigResponse.model_validate(toolkit, from_attributes=True)
    body = response.model_dump()

    assert response.has_credentials is True
    assert "credentials" not in body
    assert "owner_agent_id" not in body


def test_agent_toolkit_slug_contract_describes_non_unique_base_alias() -> None:
    """Agent-owned schemas expose a backend-materialized base alias."""
    create_description = AgentToolkitConfigCreateRequest.model_fields[
        "slug"
    ].description
    update_schema = TypeAdapter(AgentToolkitConfigUpdateRequest).json_schema()
    update_description = update_schema["properties"]["slug"]["description"]

    assert create_description is not None
    assert "non-unique base alias" in create_description
    assert "base alias" in update_description


def test_github_user_summary_redacts_all_credential_payloads() -> None:
    now = datetime.datetime.now(datetime.UTC)
    toolkit = ToolkitOutput(
        id="toolkit-user",
        workspace_id="workspace-1",
        owner_agent_id=None,
        toolkit_type="github",
        slug="github",
        name="GitHub",
        config={"github_auth_type": "github_app_user"},
        credentials='{"client_secret":"secret-client","private_key":"secret-key"}',
        enabled=True,
        always_expose_tools=False,
        revision=1,
        created_at=now,
        updated_at=now,
        github_user_connection=GitHubUserConnectionSummary(
            id="connection-1",
            account_id=123,
            account_login="execution-account",
            account_avatar_url=None,
            app_id="456",
            source="byoa_user",
            status=GitHubUserConnectionStatus.CONNECTED,
            failure_reason=None,
        ),
    )
    response = ToolkitConfigResponse.model_validate(toolkit, from_attributes=True)
    body = response.model_dump_json()
    assert "execution-account" in body
    assert "secret-client" not in body
    assert "secret-key" not in body
    assert "client_secret" not in body
    assert "private_key" not in body
    assert "access_token" not in body
    assert "cleanup_pending" not in body
