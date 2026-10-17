"""Rendered HTTP contracts for current-account personal Toolkit management."""

import datetime
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from azcommon.result import Success
from fastapi import FastAPI

from azents.api.public.toolkit.v1.personal import router
from azents.api.public.toolkit.v1.personal_oauth import router as oauth_router
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.enums import WorkspaceUserRole
from azents.core.google_oauth import GoogleOAuthError
from azents.core.personal_toolkit import (
    PersonalToolkitAccessConflict,
    PersonalToolkitAccessMutation,
    PersonalToolkitAgentIneligible,
    PersonalToolkitAuthorityDenied,
    PersonalToolkitConfigurationConflict,
    PersonalToolkitManager,
    PersonalToolkitNotFound,
    PersonalToolkitProviderAuthorityDenied,
)
from azents.core.toolkit_ownership import (
    PersonalToolkitAccess,
    PersonalToolkitAccessMode,
    ToolkitOwnerKind,
    UserToolkitOwner,
)
from azents.services.toolkit.data import PersonalToolkitOutput
from azents.services.toolkit.personal import PersonalToolkitService
from azents.services.toolkit_oauth.personal import PersonalToolkitOAuthService


def output() -> PersonalToolkitOutput:
    """Keep a fake credential in the internal source to prove response allowlisting."""
    now = datetime.datetime.now(datetime.UTC)
    return PersonalToolkitOutput(
        id="toolkit-1",
        owner=UserToolkitOwner(
            kind=ToolkitOwnerKind.USER, user_id="user-1", workspace_id="workspace-1"
        ),
        access_mode=PersonalToolkitAccessMode.ALL,
        selected_agent_ids=(),
        toolkit_type="mcp",
        slug="personal",
        name="Personal",
        config={},
        credentials='{"token":"fixture-private-value"}',
        description=None,
        prompt=None,
        enabled=True,
        always_expose_tools=True,
        revision=7,
        created_at=now,
        updated_at=now,
        oauth_connection=None,
        authorization_state=None,
        github_user_connection=None,
        readiness="ready",
    )


@pytest.fixture
def service() -> MagicMock:
    """Typed service boundary, leaving real FastAPI dependencies and response models."""
    service = MagicMock(spec=PersonalToolkitService)
    service.list = AsyncMock(return_value=[output()])
    service.get = AsyncMock(return_value=output())
    service.create = AsyncMock(return_value=Success(output()))
    service.update = AsyncMock(return_value=Success(output()))
    service.delete = AsyncMock()
    service.agent_connections = AsyncMock(return_value=[output()])
    service.mutate_access = AsyncMock(
        return_value=[
            PersonalToolkitAccess(
                "toolkit-1",
                "user-1",
                "workspace-1",
                PersonalToolkitAccessMode.SELECTED,
                ("agent-2",),
            )
        ]
    )
    return service


@pytest.fixture
async def client(service: MagicMock) -> AsyncIterator[httpx.AsyncClient]:
    """Use the actual personal routes and HTTP validation/serialization surface."""
    app = FastAPI()
    app.include_router(router, prefix="/toolkit/v1")
    app.include_router(oauth_router, prefix="/toolkit/v1")
    app.dependency_overrides[PersonalToolkitService] = lambda: service
    oauth_service = MagicMock(spec=PersonalToolkitOAuthService)
    oauth_service.exchange = AsyncMock()
    app.dependency_overrides[PersonalToolkitOAuthService] = lambda: oauth_service
    app.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="user-1",
        session_id="auth-1",
        workspace_id="workspace-1",
        workspace_user_id="member-1",
        role=WorkspaceUserRole.MEMBER,
        permissions=set(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.parametrize(
    "path",
    [
        "/personal-toolkit-configs",
        "/personal-toolkit-configs/toolkit-1",
        "/agents/agent-1/personal-toolkit-access",
    ],
)
async def test_responses_expose_scoped_owner_without_internal_credentials(
    client: httpx.AsyncClient, path: str
) -> None:
    """All read entries project safe metadata with explicit personal ownership."""
    response = await client.get("/toolkit/v1/workspaces/workspace-one" + path)
    assert response.status_code == 200
    body = response.json()
    item = body["items"][0] if "items" in body else body
    assert item["owner"] == {
        "kind": "user",
        "user_id": "user-1",
        "workspace_id": "workspace-1",
    }
    assert item["has_credentials"] is True and item["access_mode"] == "all"
    assert item["always_expose_tools"] is True
    assert "credentials" not in item and "workspace_id" not in item
    assert "encrypted_credentials" not in item and "revision" not in item
    assert "fixture-private-value" not in response.text


async def test_create_derives_owner_only_from_current_authentication(
    client: httpx.AsyncClient, service: MagicMock
) -> None:
    """Client JSON cannot forge an owner or an owning Workspace."""
    request = {
        "toolkit_type": "mcp",
        "name": "Personal",
        "config": {},
        "always_expose_tools": True,
    }
    response = await client.post(
        "/toolkit/v1/workspaces/workspace-one/personal-toolkit-configs", json=request
    )
    assert response.status_code == 201
    args = service.create.await_args.args
    assert args[0] == PersonalToolkitManager("user-1", "auth-1", "workspace-1")
    assert args[1].always_expose_tools is True
    for injected in (
        {"owner_user_id": "user-2"},
        {"workspace_id": "workspace-2"},
        {"owner": {"kind": "user", "user_id": "user-2"}},
    ):
        forged = await client.post(
            "/toolkit/v1/workspaces/workspace-one/personal-toolkit-configs",
            json={**request, **injected},
        )
        assert forged.status_code == 422
    assert service.create.await_count == 1


async def test_connection_editor_sends_required_expected_mode_and_deltas(
    client: httpx.AsyncClient, service: MagicMock
) -> None:
    """Search UI cannot replace unseen membership through a full selection payload."""
    payload = {
        "expected_mode": "all",
        "mode": None,
        "allow_agent_ids": [],
        "restrict_agent_ids": ["agent-1"],
    }
    response = await client.patch(
        "/toolkit/v1/workspaces/workspace-one/personal-toolkit-configs/toolkit-1/agent-access",
        json=payload,
    )
    assert response.status_code == 200
    assert response.json() == {
        "toolkit_id": "toolkit-1",
        "mode": "selected",
        "selected_agent_ids": ["agent-2"],
    }
    service.mutate_access.assert_awaited_once_with(
        PersonalToolkitManager("user-1", "auth-1", "workspace-1"),
        [
            PersonalToolkitAccessMutation(
                "toolkit-1",
                None,
                frozenset(),
                frozenset(["agent-1"]),
                PersonalToolkitAccessMode.ALL,
            )
        ],
        agent_id=None,
    )
    for malformed in (
        {"selected_agent_ids": ["agent-1"]},
        {"mode": "selected", "allow_agent_ids": [], "restrict_agent_ids": []},
    ):
        bad = await client.patch(
            "/toolkit/v1/workspaces/workspace-one/personal-toolkit-configs/toolkit-1/agent-access",
            json=malformed,
        )
        assert bad.status_code == 422
    assert service.mutate_access.await_count == 1


async def test_agent_editor_cannot_reset_global_mode_or_duplicate_target(
    client: httpx.AsyncClient, service: MagicMock
) -> None:
    """Agent save is a single atomic delta-only intent bound to its path identity."""
    entry = {
        "toolkit_id": "toolkit-1",
        "expected_mode": "selected",
        "mode": None,
        "allow_agent_ids": ["agent-1"],
        "restrict_agent_ids": [],
    }
    response = await client.patch(
        "/toolkit/v1/workspaces/workspace-one/agents/agent-1/personal-toolkit-access",
        json={"mutations": [entry]},
    )
    assert response.status_code == 200
    assert service.mutate_access.await_args.kwargs == {"agent_id": "agent-1"}
    for invalid in (
        [entry, entry],
        [{**entry, "mode": "all", "allow_agent_ids": []}],
        [{**entry, "restrict_agent_ids": ["agent-1"]}],
    ):
        bad = await client.patch(
            "/toolkit/v1/workspaces/workspace-one/agents/agent-1/personal-toolkit-access",
            json={"mutations": invalid},
        )
        assert bad.status_code == 422
    assert service.mutate_access.await_count == 1


@pytest.mark.parametrize(
    "error,expected",
    [
        (PersonalToolkitNotFound("foreign"), 404),
        (PersonalToolkitAgentIneligible("foreign"), 404),
        (PersonalToolkitAuthorityDenied("inactive"), 401),
        (PersonalToolkitProviderAuthorityDenied("provider"), 403),
        (PersonalToolkitConfigurationConflict("changed"), 409),
        (PersonalToolkitAccessConflict("changed"), 409),
        (GoogleOAuthError("not_authenticated", "Not authenticated."), 401),
        (GoogleOAuthError("not_found", "Connection not found."), 404),
    ],
)
async def test_expected_failures_remain_denials_or_conflicts(
    client: httpx.AsyncClient, service: MagicMock, error: Exception, expected: int
) -> None:
    service.get.side_effect = error
    response = await client.get(
        "/toolkit/v1/workspaces/workspace-one/personal-toolkit-configs/toolkit-1"
    )
    assert response.status_code == expected
    assert "foreign" not in response.text


async def test_unexpected_internal_error_is_not_a_success_payload(
    client: httpx.AsyncClient, service: MagicMock
) -> None:
    service.get.side_effect = RuntimeError("fixture programming failure")
    with pytest.raises(RuntimeError, match="programming failure"):
        await client.get(
            "/toolkit/v1/workspaces/workspace-one/personal-toolkit-configs/toolkit-1"
        )


async def test_validation_never_echoes_credentials_or_callback_secrets(
    client: httpx.AsyncClient,
) -> None:
    """Invalid credentials/callback shapes fail without retaining submitted secrets."""
    create = await client.post(
        "/toolkit/v1/workspaces/workspace-one/personal-toolkit-configs",
        json={
            "toolkit_type": "mcp",
            "config": {},
            "always_expose_tools": True,
            "credentials": "fixture-private-credential",
        },
    )
    callback = await client.post(
        "/toolkit/v1/workspaces/workspace-one/personal-toolkit-configs/toolkit-1/oauth/exchange",
        json={
            "code": "fixture-private-code",
            "state": 123,
            "unexpected": "fixture-private-state",
        },
    )
    for response in (create, callback):
        assert response.status_code == 422
        assert "fixture-private" not in response.text
        assert "input" not in response.text


def test_real_openapi_keeps_shared_workspace_and_redacts_personal(
    full_public_openapi: dict[str, Any],
) -> None:
    """The application graph adds personal routes without weakening shared DTOs."""
    schema = full_public_openapi
    models = schema["components"]["schemas"]
    assert "workspace_id" in models["ToolkitConfigResponse"]["required"]
    properties = models["PersonalToolkitResponse"]["properties"]
    assert "workspace_id" not in properties and "credentials" not in properties
    assert "owner" in properties and "access_mode" in properties
    path = "/toolkit/v1/workspaces/{handle}/personal-toolkit-configs"
    assert path in schema["paths"]
