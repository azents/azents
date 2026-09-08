import datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from azents.api.public.toolkit.v1.data import (
    AgentToolkitConfigCreateRequest,
    AgentToolkitConfigUpdateRequest,
    ToolkitConfigCreateRequest,
    ToolkitConfigResponse,
    ToolkitConfigUpdateRequest,
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


def test_toolkit_config_create_request_rejects_dash_slug() -> None:
    with pytest.raises(ValidationError):
        ToolkitConfigCreateRequest(
            toolkit_type="kubernetes",
            slug="home-kubernetes",
            name="Home Kubernetes",
            config={},
        )


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


def test_toolkit_config_update_request_rejects_dash_slug() -> None:
    adapter: TypeAdapter[ToolkitConfigUpdateRequest] = TypeAdapter(
        ToolkitConfigUpdateRequest
    )

    with pytest.raises(ValidationError):
        adapter.validate_python({"slug": "home-kubernetes"})


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


def test_agent_toolkit_slug_contract_describes_agent_local_namespace() -> None:
    """Agent-owned create and update schemas document the effective Agent namespace."""
    create_description = AgentToolkitConfigCreateRequest.model_fields[
        "slug"
    ].description
    update_schema = TypeAdapter(AgentToolkitConfigUpdateRequest).json_schema()
    update_description = update_schema["properties"]["slug"]["description"]

    assert create_description is not None
    assert "owning Agent" in create_description
    assert "owning Agent" in update_description
