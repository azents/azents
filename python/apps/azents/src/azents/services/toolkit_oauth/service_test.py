"""Service external-effect ordering with completed-operation boundary doubles.

These doubles witness application sequencing, not PostgreSQL atomicity or
serialization. The repository suite separately supplies genuine SQL evidence.
"""

import asyncio
import dataclasses
import datetime
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NoReturn
from unittest.mock import Mock, create_autospec
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from azcommon.result import Failure, Result, Success
from fastapi import HTTPException

from azents.api.public.toolkit.v1 import oauth
from azents.core import tools
from azents.core.account_access import ActiveAccountSubjectStatus
from azents.core.auth.deps import WorkspaceMember
from azents.core.auth.roles import get_permissions_for_role
from azents.core.config import Config, CredentialEncryptionConfig
from azents.core.enums import MCPOAuthConnectionStatus, WorkspaceUserRole
from azents.core.mcp_discovery import (
    DcrError,
    DcrRegistrationResult,
    DiscoveryError,
    OAuthServerMetadata,
)
from azents.core.oauth2 import (
    OAuthTokenResponse,
    create_agent_github_platform_oauth_state,
    create_platform_oauth_state,
    create_toolkit_oauth_state,
)
from azents.core.system_setting import SystemSettingFieldSource
from azents.engine.tools.mcp import McpToolkitProvider
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnection
from azents.repos.toolkit.data import ToolkitConfig
from azents.repos.toolkit_oauth_data import (
    GithubInstallationRecord,
    SharedOAuthContext,
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
from azents.services.toolkit_oauth import helpers
from azents.services.toolkit_oauth import service as service_module
from azents.services.toolkit_oauth.data import (
    ToolkitConnectionTestInput,
    ToolkitOAuthError,
)
from azents.services.toolkit_oauth.service import ToolkitOAuthService


@pytest.fixture(autouse=True)
def _no_provider_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every missing external mock fail locally before any network attempt."""

    def reject_client(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("External collaborator was not explicitly mocked.")

    monkeypatch.setattr(httpx, "AsyncClient", reject_client)


@dataclasses.dataclass
class _Boundary:
    """Observe only a typed completed-operation double's enter/finish boundary."""

    active: bool
    calls: list[str]
    stores: list[OAuthConnectionWrite]
    synced: list[tuple[GithubInstallationRecord, ...]]
    requesters: list[ToolkitOAuthRequester]

    @asynccontextmanager
    async def operation(self, name: str) -> AsyncIterator[None]:
        assert not self.active
        self.active = True
        self.calls.append(f"{name}:open")
        try:
            yield
        finally:
            self.active = False
            self.calls.append(f"{name}:closed")

    def external(self, name: str) -> None:
        assert not self.active, f"{name} ran before a completed-operation return"
        self.calls.append(name)


@dataclasses.dataclass(frozen=True)
class _Harness:
    """Actual service and strict completed collaborator mocks with witnesses."""

    service: ToolkitOAuthService
    repository: Mock
    runtime: Mock
    boundary: _Boundary


def _toolkit(credentials: str | None) -> ToolkitConfig:
    now = datetime.datetime.now(datetime.UTC)
    return ToolkitConfig(
        id="toolkit-1",
        workspace_id="workspace-1",
        owner_agent_id=None,
        toolkit_type="mcp",
        slug="shared",
        name="Shared MCP",
        config={"server_url": "https://mcp.test", "auth_type": "oauth2"},
        credentials=credentials,
        enabled=True,
        always_expose_tools=False,
        revision=1,
        created_at=now,
        updated_at=now,
    )


def _connection() -> MCPOAuthConnection:
    now = datetime.datetime.now(datetime.UTC)
    return MCPOAuthConnection(
        id="connection-1",
        toolkit_id="toolkit-1",
        issuer="https://issuer.test",
        resource=None,
        server_url="https://mcp.test",
        authorization_endpoint="https://mcp.test/authorize",
        token_endpoint="https://mcp.test/token",
        registration_endpoint=None,
        client_id="existing-client",
        client_secret="existing-secret",
        token_endpoint_auth_method="client_secret_post",
        scope="existing-scope",
        access_token="existing-access",
        refresh_token="existing-refresh",
        expires_at=now + datetime.timedelta(hours=1),
        status=MCPOAuthConnectionStatus.CONNECTED,
        created_at=now,
        updated_at=now,
    )


def _harness(
    context: SharedOAuthContext,
    outcome: Result[None, ToolkitOAuthDenied],
) -> _Harness:
    """Make required collaborators; no raw Session or application factory double."""
    boundary = _Boundary(False, [], [], [], [])
    repository = create_autospec(ToolkitOAuthOperationRepository, instance=True)

    async def read_context(*, toolkit_id: str) -> SharedOAuthContext:
        assert toolkit_id == "toolkit-1"
        async with boundary.operation("context"):
            return context

    async def store(
        *,
        requester: ToolkitOAuthRequester,
        toolkit_id: str,
        connection: OAuthConnectionWrite,
    ) -> Result[None, ToolkitOAuthDenied]:
        assert toolkit_id == "toolkit-1"
        async with boundary.operation("store"):
            boundary.requesters.append(requester)
            if outcome.success:
                boundary.stores.append(connection)
            return outcome

    async def sync(
        *,
        requester: ToolkitOAuthRequester,
        platform_app_id: str,
        installations: tuple[GithubInstallationRecord, ...],
    ) -> Result[None, ToolkitOAuthDenied]:
        assert platform_app_id == "123"
        async with boundary.operation("sync"):
            boundary.requesters.append(requester)
            if outcome.success:
                boundary.synced.append(installations)
            return outcome

    async def delete(
        *, workspace_id: str, toolkit_id: str
    ) -> Result[None, ToolkitOAuthDenied]:
        assert (workspace_id, toolkit_id) == ("workspace-1", "toolkit-1")
        async with boundary.operation("delete"):
            return outcome

    async def read_toolkit(
        *, workspace_id: str, toolkit_id: str
    ) -> ToolkitConfig | None:
        assert (workspace_id, toolkit_id) == ("workspace-1", "toolkit-1")
        async with boundary.operation("toolkit"):
            return context.toolkit

    async def read_optional(
        *, workspace_id: str, toolkit_id: str | None
    ) -> ToolkitConfig | None:
        if toolkit_id is None:
            assert not boundary.active
            boundary.calls.append("optional:none")
            return None
        return await read_toolkit(workspace_id=workspace_id, toolkit_id=toolkit_id)

    repository.read_shared_context.side_effect = read_context
    repository.store_shared_connection.side_effect = store
    repository.sync_installations.side_effect = sync
    repository.delete_shared_connection.side_effect = delete
    repository.read_shared_toolkit.side_effect = read_toolkit
    repository.read_optional_shared_toolkit.side_effect = read_optional
    runtime = create_autospec(PlatformGitHubAppRuntimeService, instance=True)

    async def resolve() -> ResolvedPlatformGitHubApp:
        boundary.external("platform")
        return ResolvedPlatformGitHubApp(
            app_id="123",
            client_id="platform-client",
            client_secret="platform-secret",
            private_key=None,
            app_id_source=SystemSettingFieldSource.ADMIN,
            effective_generation="generation-1",
        )

    runtime.resolve.side_effect = resolve
    service = ToolkitOAuthService(
        repository=repository,
        config=Config.model_construct(
            web_url="https://app.test",
            mcp_proxy_url=None,
            credential_encryption=CredentialEncryptionConfig(key="state-secret"),
        ),
        registry={"mcp": McpToolkitProvider()},
        platform_runtime=runtime,
    )
    return _Harness(service, repository, runtime, boundary)


def _member(role: WorkspaceUserRole) -> WorkspaceMember:
    return WorkspaceMember(
        user_id="user-1",
        session_id="session-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=role,
        permissions=get_permissions_for_role(role),
    )


def _metadata() -> OAuthServerMetadata:
    return OAuthServerMetadata(
        authorization_endpoint="https://mcp.test/authorize",
        token_endpoint="https://mcp.test/token",
        registration_endpoint="https://mcp.test/register",
        issuer="https://issuer.test",
        scopes_supported=[],
    )


def _patch_discovery(monkeypatch: pytest.MonkeyPatch, boundary: _Boundary) -> None:
    async def discover(*args: object, **kwargs: object) -> OAuthServerMetadata:
        boundary.external("metadata")
        return _metadata()

    monkeypatch.setattr(helpers, "discover_oauth_metadata", discover)


async def test_connect_metadata_dcr_store_and_public_reply_follow_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route/service/helpers preserve first-connect order and no-token writes."""
    harness = _harness(SharedOAuthContext(_toolkit(None), None), Success(None))
    _patch_discovery(monkeypatch, harness.boundary)

    async def register(*args: object, **kwargs: object) -> DcrRegistrationResult:
        harness.boundary.external("dcr")
        return DcrRegistrationResult(client_id="dcr-client", client_secret=None)

    monkeypatch.setattr(service_module, "register_client", register)
    response_model = oauth.OAuthAuthorizeResponse

    def reply(*, authorization_url: str) -> oauth.OAuthAuthorizeResponse:
        harness.boundary.external("reply")
        return response_model(authorization_url=authorization_url)

    monkeypatch.setattr(oauth, "OAuthAuthorizeResponse", reply)
    response = await oauth.connect_oauth(
        _member(WorkspaceUserRole.MANAGER),
        harness.service,
        handle="workspace",
        toolkit_config_id="toolkit-1",
    )
    assert response.authorization_url.startswith("https://mcp.test/authorize?")
    assert harness.boundary.calls == [
        "context:open",
        "context:closed",
        "metadata",
        "dcr",
        "store:open",
        "store:closed",
        "reply",
    ]
    write = harness.boundary.stores[0]
    assert write.access_token is None
    assert write.refresh_token is None
    assert write.expires_at is None
    assert write.token_endpoint_auth_method == "none"
    assert harness.boundary.requesters == [
        ToolkitOAuthRequester("user-1", "session-1", "workspace-1")
    ]


async def test_connect_carries_existing_tokens_even_with_changed_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setup is a full captured-field store, not config/token CAS or refresh policy."""
    existing = _connection()
    harness = _harness(SharedOAuthContext(_toolkit(None), existing), Success(None))
    _patch_discovery(monkeypatch, harness.boundary)
    await harness.service.connect(
        user_id="user-1",
        session_id="session-1",
        workspace_id="workspace-1",
        handle="workspace",
        toolkit_id="toolkit-1",
    )
    write = harness.boundary.stores[0]
    assert (write.access_token, write.refresh_token, write.expires_at) == (
        existing.access_token,
        existing.refresh_token,
        existing.expires_at,
    )
    assert write.client_id == existing.client_id
    assert "dcr" not in harness.boundary.calls


async def test_shared_exchange_ignores_state_user_and_uses_stored_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Captured registration fields remain; missing exchanged refresh clears it."""
    connection = _connection()
    harness = _harness(SharedOAuthContext(_toolkit(None), connection), Success(None))
    state = create_toolkit_oauth_state(
        toolkit_id="toolkit-1",
        workspace_id="workspace-1",
        user_id="other-initiating-user",
        redirect_uri="https://previous.test/callback?handle=old",
        code_verifier="saved-verifier",
        secret_key="state-secret",
    )

    async def token(**kwargs: object) -> OAuthTokenResponse:
        harness.boundary.external("token")
        assert kwargs["redirect_uri"] == "https://previous.test/callback?handle=old"
        assert kwargs["code_verifier"] == "saved-verifier"
        assert kwargs["resource"] == "https://mcp.test"
        return OAuthTokenResponse(access_token="exchanged-access")

    monkeypatch.setattr(helpers, "exchange_authorization_code", token)
    await oauth.exchange_oauth_connection(
        _member(WorkspaceUserRole.MANAGER),
        harness.service,
        oauth.OAuthExchangeRequest(code="code", state=state),
        handle="renamed",
        toolkit_config_id="toolkit-1",
    )
    write = harness.boundary.stores[0]
    assert write.client_id == connection.client_id
    assert write.server_url == connection.server_url
    assert write.access_token == "exchanged-access"
    assert write.refresh_token is None
    assert harness.boundary.calls == [
        "context:open",
        "context:closed",
        "token",
        "store:open",
        "store:closed",
    ]


@pytest.mark.parametrize("stage", ["metadata", "dcr", "token"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_external_failure_or_cancellation_never_starts_final_store(
    monkeypatch: pytest.MonkeyPatch, stage: str, cancel: bool
) -> None:
    """Read completion precedes every external failure/cancel without a later write."""
    connection = _connection() if stage == "token" else None
    harness = _harness(SharedOAuthContext(_toolkit(None), connection), Success(None))
    _patch_discovery(monkeypatch, harness.boundary)
    failure = asyncio.CancelledError() if cancel else RuntimeError("external failure")

    async def fail(*args: object, **kwargs: object) -> object:
        harness.boundary.external(stage)
        raise failure

    if stage == "metadata":
        monkeypatch.setattr(helpers, "discover_oauth_metadata", fail)
    elif stage == "dcr":
        monkeypatch.setattr(service_module, "register_client", fail)
    else:
        monkeypatch.setattr(helpers, "exchange_authorization_code", fail)
    with pytest.raises(type(failure)) as raised:
        if stage == "token":
            await harness.service.exchange(
                user_id="user-1",
                session_id="session-1",
                workspace_id="workspace-1",
                toolkit_id="toolkit-1",
                code="code",
                state=create_toolkit_oauth_state(
                    toolkit_id="toolkit-1",
                    workspace_id="workspace-1",
                    user_id="user-1",
                    redirect_uri="https://app.test/callback",
                    code_verifier="verifier",
                    secret_key="state-secret",
                ),
            )
        else:
            await harness.service.connect(
                user_id="user-1",
                session_id="session-1",
                workspace_id="workspace-1",
                handle="workspace",
                toolkit_id="toolkit-1",
            )
    assert raised.value is failure
    assert not harness.boundary.active
    assert harness.boundary.stores == []
    harness.repository.store_shared_connection.assert_not_awaited()


@pytest.mark.parametrize(
    ("reason", "status_code", "detail"),
    [
        (ToolkitOAuthDenialReason.INACTIVE_SUBJECT, 401, "Not authenticated"),
        (ToolkitOAuthDenialReason.WORKSPACE_NOT_FOUND, 404, "Workspace not found."),
        (
            ToolkitOAuthDenialReason.MEMBERSHIP_REQUIRED,
            403,
            "Not a member of this workspace.",
        ),
        (
            ToolkitOAuthDenialReason.WRITE_PERMISSION_REQUIRED,
            403,
            "Toolkit write permission required.",
        ),
        (
            ToolkitOAuthDenialReason.TOOLKIT_NOT_FOUND,
            404,
            "Toolkit config not found.",
        ),
    ],
)
async def test_final_authority_denial_projects_only_after_completed_store(
    monkeypatch: pytest.MonkeyPatch,
    reason: ToolkitOAuthDenialReason,
    status_code: int,
    detail: str,
) -> None:
    """Expected approved final outcomes retain exact API status and Bearer challenge."""
    harness = _harness(
        SharedOAuthContext(
            _toolkit('{"type":"oauth2","client_id":"manual","client_secret":"secret"}'),
            None,
        ),
        Failure(
            ToolkitOAuthDenied(
                reason,
                (
                    ActiveAccountSubjectStatus.SESSION_REVOKED
                    if reason is ToolkitOAuthDenialReason.INACTIVE_SUBJECT
                    else None
                ),
            )
        ),
    )
    _patch_discovery(monkeypatch, harness.boundary)
    with pytest.raises(HTTPException) as raised:
        await oauth.connect_oauth(
            _member(WorkspaceUserRole.OWNER),
            harness.service,
            handle="workspace",
            toolkit_config_id="toolkit-1",
        )
    assert raised.value.status_code == status_code
    assert raised.value.detail == detail
    assert raised.value.headers == (
        {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    )
    assert harness.boundary.calls[-1] == "store:closed"
    assert not harness.boundary.active
    assert harness.boundary.stores == []


@pytest.mark.parametrize("cancel", [False, True])
async def test_unexpected_completed_store_error_propagates_without_4xx_conversion(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    """Cipher/database errors stay transparent after completed-operation cleanup."""
    harness = _harness(SharedOAuthContext(_toolkit(None), _connection()), Success(None))
    _patch_discovery(monkeypatch, harness.boundary)
    failure = asyncio.CancelledError() if cancel else ValueError("cipher failed")

    async def fail_store(**kwargs: object) -> Result[None, ToolkitOAuthDenied]:
        async with harness.boundary.operation("store"):
            raise failure

    harness.repository.store_shared_connection.side_effect = fail_store
    with pytest.raises(type(failure)) as raised:
        await oauth.connect_oauth(
            _member(WorkspaceUserRole.OWNER),
            harness.service,
            handle="workspace",
            toolkit_config_id="toolkit-1",
        )
    assert raised.value is failure
    assert not harness.boundary.active
    assert harness.boundary.calls[-1] == "store:closed"


@pytest.mark.parametrize(
    ("failure_stage", "cancel"),
    [(None, False), ("list", False), ("list", True), ("sync", False), ("sync", True)],
)
async def test_workspace_installation_revoke_is_success_only_and_after_sync(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str | None,
    cancel: bool,
) -> None:
    """Closed boundaries retain success-only Workspace revoke on error/cancel."""
    harness = _harness(SharedOAuthContext(None, None), Success(None))
    failure = asyncio.CancelledError() if cancel else RuntimeError("failed stage")

    async def exchange(*args: object) -> str:
        harness.boundary.external("github-token")
        return "temporary-token"

    async def installations(*args: object) -> list[dict[str, object]]:
        harness.boundary.external("list")
        if failure_stage == "list":
            raise failure
        return [
            {"id": 1, "account": {"login": "missing-avatar", "type": "User"}},
            {
                "id": 1,
                "account": {"login": "last", "type": "User", "avatar_url": "avatar"},
            },
        ]

    async def revoke(*args: object) -> None:
        harness.boundary.external("revoke")

    monkeypatch.setattr(service_module, "exchange_oauth_code", exchange)
    monkeypatch.setattr(service_module, "list_user_installations", installations)
    monkeypatch.setattr(service_module, "revoke_oauth_token", revoke)
    if failure_stage == "sync":

        async def fail_sync(**kwargs: object) -> Result[None, ToolkitOAuthDenied]:
            async with harness.boundary.operation("sync"):
                raise failure

        harness.repository.sync_installations.side_effect = fail_sync
    state = create_platform_oauth_state(
        "state-secret", effective_generation="generation-1"
    )
    if failure_stage is not None:
        with pytest.raises(type(failure)) as raised:
            await harness.service.platform_installations(
                user_id="user-1",
                session_id="session-1",
                workspace_id="workspace-1",
                code="code",
                state=state,
            )
        assert raised.value is failure
        assert "revoke" not in harness.boundary.calls
    else:
        response = await oauth.get_github_platform_installations(
            _member(WorkspaceUserRole.MANAGER),
            harness.service,
            oauth.GitHubPlatformInstallationsRequest(code="code", state=state),
            handle="workspace",
        )
        assert [item.account_login for item in response.installations] == ["last"]
        assert harness.boundary.synced == [
            (
                GithubInstallationRecord(1, "missing-avatar", "User", ""),
                GithubInstallationRecord(1, "last", "User", "avatar"),
            )
        ]
        assert harness.boundary.calls == [
            "platform",
            "github-token",
            "list",
            "sync:open",
            "sync:closed",
            "revoke",
        ]
    assert not harness.boundary.active


@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
async def test_provider_test_failure_and_cancel_follow_completed_snapshot(
    monkeypatch: pytest.MonkeyPatch, saved: bool, cancel: bool
) -> None:
    """Saved and form-only provider tests never borrow a database lifetime."""
    toolkit = _toolkit('{"type":"bearer","token":"saved"}') if saved else None
    harness = _harness(SharedOAuthContext(toolkit, None), Success(None))
    failure = asyncio.CancelledError() if cancel else RuntimeError("provider failure")

    async def test_provider(
        config: tools.McpToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None,
    ) -> tools.TestConnectionResult:
        harness.boundary.external("provider")
        assert credentials_json is not None
        assert json.loads(credentials_json)["token"] == ("saved" if saved else "form")
        raise failure

    monkeypatch.setattr(
        harness.service.registry["mcp"], "test_connection", test_provider
    )
    with pytest.raises(type(failure)) as raised:
        if saved:
            await harness.service.test_saved(
                workspace_id="workspace-1", toolkit_id="toolkit-1"
            )
        else:
            await harness.service.test_unsaved(
                workspace_id="workspace-1",
                request=ToolkitConnectionTestInput(
                    "mcp",
                    {"server_url": "https://mcp.test", "auth_type": "bearer"},
                    {"type": "bearer", "token": "form"},
                    None,
                ),
            )
    assert raised.value is failure
    assert not harness.boundary.active
    assert harness.boundary.calls == (
        ["toolkit:open", "toolkit:closed", "provider"]
        if saved
        else ["optional:none", "provider"]
    )


async def test_unsaved_ineligible_id_remains_form_only_and_saved_is_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional missing saved lookup never changes provider/form fallback policy."""
    harness = _harness(SharedOAuthContext(None, None), Success(None))

    async def test_provider(
        config: tools.McpToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None,
    ) -> tools.TestConnectionResult:
        harness.boundary.external("provider")
        assert credentials_json == '{"type": "bearer", "token": ""}'
        return tools.TestConnectionResult(True, "ok", None, None, None)

    monkeypatch.setattr(
        harness.service.registry["mcp"], "test_connection", test_provider
    )
    result = await harness.service.test_unsaved(
        workspace_id="workspace-1",
        request=ToolkitConnectionTestInput(
            "mcp",
            {"server_url": "https://mcp.test", "auth_type": "bearer"},
            {"type": "bearer", "token": ""},
            "toolkit-1",
        ),
    )
    assert result.success
    with pytest.raises(ToolkitOAuthError) as missing:
        await harness.service.test_saved(
            workspace_id="workspace-1", toolkit_id="toolkit-1"
        )
    assert missing.value.detail == "Toolkit config not found."
    assert not harness.boundary.active


async def test_disconnect_absent_connection_noop_returns_after_completion() -> None:
    """Idempotent completed delete returns without provider effects."""
    harness = _harness(SharedOAuthContext(_toolkit(None), None), Success(None))
    await oauth.disconnect_oauth_connection(
        _member(WorkspaceUserRole.OWNER),
        harness.service,
        handle="workspace",
        toolkit_config_id="toolkit-1",
    )
    assert harness.boundary.calls == ["delete:open", "delete:closed"]
    assert not harness.boundary.active


async def test_permission_denial_stops_service_and_external_work() -> None:
    """Ingress Toolkit write is checked before the service receives any work."""
    harness = _harness(SharedOAuthContext(_toolkit(None), None), Success(None))
    with pytest.raises(HTTPException) as denied:
        await oauth.connect_oauth(
            _member(WorkspaceUserRole.MEMBER),
            harness.service,
            handle="workspace",
            toolkit_config_id="toolkit-1",
        )
    assert denied.value.status_code == 403
    assert harness.boundary.calls == []
    harness.repository.read_shared_context.assert_not_awaited()


@pytest.mark.parametrize("failure_kind", ["discovery", "dcr"])
async def test_expected_setup_errors_preserve_api_400_after_read_closure(
    monkeypatch: pytest.MonkeyPatch, failure_kind: str
) -> None:
    """Canonical expected helper failures retain their original API projection."""
    harness = _harness(SharedOAuthContext(_toolkit(None), None), Success(None))
    _patch_discovery(monkeypatch, harness.boundary)

    async def fail_discovery(*args: object, **kwargs: object) -> OAuthServerMetadata:
        harness.boundary.external("metadata")
        raise DiscoveryError("discovery failed")

    async def fail_dcr(*args: object, **kwargs: object) -> DcrRegistrationResult:
        harness.boundary.external("dcr")
        raise DcrError("dcr failed")

    if failure_kind == "discovery":
        monkeypatch.setattr(helpers, "discover_oauth_metadata", fail_discovery)
        detail = "OAuth metadata discovery failed: discovery failed"
    else:
        monkeypatch.setattr(service_module, "register_client", fail_dcr)
        detail = "Dynamic client registration failed: dcr failed"
    with pytest.raises(HTTPException) as rejected:
        await oauth.connect_oauth(
            _member(WorkspaceUserRole.OWNER),
            harness.service,
            handle="workspace",
            toolkit_config_id="toolkit-1",
        )
    assert rejected.value.status_code == 400
    assert rejected.value.detail == detail
    assert not harness.boundary.active
    assert harness.boundary.stores == []


async def test_platform_credential_binding_follows_optional_read_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Platform identity resolution occurs after form-only completed read/no-op."""
    harness = _harness(SharedOAuthContext(None, None), Success(None))

    async def test_provider(
        config: tools.McpToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None,
    ) -> tools.TestConnectionResult:
        harness.boundary.external("provider")
        assert credentials_json is not None
        assert json.loads(credentials_json)["app_id"] == "123"
        return tools.TestConnectionResult(True, "ok", None, None, None)

    monkeypatch.setattr(
        harness.service.registry["mcp"], "test_connection", test_provider
    )
    result = await harness.service.test_unsaved(
        workspace_id="workspace-1",
        request=ToolkitConnectionTestInput(
            "mcp",
            {"server_url": "https://mcp.test", "auth_type": "none"},
            {"type": "github_app_platform", "app_id": "old", "installations": []},
            None,
        ),
    )
    assert result.success
    assert harness.boundary.calls == ["optional:none", "platform", "provider"]
    assert (
        await helpers.bind_platform_app_test_credentials(
            None, harness.service.platform_runtime
        )
        is None
    )
    assert harness.boundary.calls == ["optional:none", "platform", "provider"]


async def test_shared_connect_state_keeps_exact_path_and_existing_callback_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shared callback state retains the same path/redirect construction."""
    harness = _harness(
        SharedOAuthContext(
            _toolkit('{"type":"oauth2","client_id":"manual","client_secret":"secret"}'),
            None,
        ),
        Success(None),
    )
    _patch_discovery(monkeypatch, harness.boundary)
    url = await harness.service.connect(
        user_id="user-1",
        session_id="session-1",
        workspace_id="workspace-1",
        handle="workspace",
        toolkit_id="toolkit-1",
    )
    params = parse_qs(urlsplit(url).query)
    assert params["redirect_uri"] == [
        "https://app.test/oauth/mcp/callback?handle=workspace&toolkit_config_id=toolkit-1"
    ]
    assert params["client_id"] == ["manual"]
    assert params["code_challenge_method"] == ["S256"]


async def test_github_list_http_error_remains_transparent_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the existing GitHub HTTP classification wraps list errors."""
    harness = _harness(SharedOAuthContext(None, None), Success(None))

    async def exchange(*args: object) -> str:
        harness.boundary.external("github-token")
        return "temporary-token"

    async def installations(*args: object) -> list[dict[str, object]]:
        harness.boundary.external("list")
        raise httpx.HTTPStatusError(
            "failure",
            request=httpx.Request("GET", "https://api.github.test/user/installations"),
            response=httpx.Response(503),
        )

    monkeypatch.setattr(service_module, "exchange_oauth_code", exchange)
    monkeypatch.setattr(service_module, "list_user_installations", installations)
    with pytest.raises(
        RuntimeError, match="Failed to fetch user installations: HTTP 503"
    ):
        await harness.service.platform_installations(
            user_id="user-1",
            session_id="session-1",
            workspace_id="workspace-1",
            code="code",
            state=create_platform_oauth_state(
                "state-secret", effective_generation="generation-1"
            ),
        )
    harness.repository.sync_installations.assert_not_awaited()
    assert not harness.boundary.active


@pytest.mark.parametrize(
    ("stage", "cancel"),
    [
        ("list", False),
        ("list", True),
        ("sync", False),
        ("sync", True),
        ("denied", False),
    ],
)
async def test_agent_installation_finally_revoke_preserves_error_cancel_asymmetry(
    monkeypatch: pytest.MonkeyPatch, stage: str, cancel: bool
) -> None:
    """Agent keeps finally revoke after list/sync error, cancel or domain denial."""
    harness = _harness(SharedOAuthContext(None, None), Success(None))
    toolkit_service = create_autospec(ToolkitService, instance=True)
    failure = asyncio.CancelledError() if cancel else RuntimeError("agent failure")

    async def authorize(*args: object, **kwargs: object) -> Result[None, NotAdmin]:
        async with harness.boundary.operation("agent-authorize"):
            return Success(None)

    async def sync(*args: object, **kwargs: object) -> Result[None, NotAdmin]:
        async with harness.boundary.operation("agent-sync"):
            if stage == "sync":
                raise failure
            if stage == "denied":
                return Failure(NotAdmin(agent_id="agent-1"))
            return Success(None)

    toolkit_service.authorize_agent_management.side_effect = authorize
    toolkit_service.sync_agent_github_installations.side_effect = sync

    async def exchange(*args: object) -> str:
        harness.boundary.external("github-token")
        return "temporary-token"

    async def installations(*args: object) -> list[dict[str, object]]:
        harness.boundary.external("list")
        if stage == "list":
            raise failure
        return []

    async def revoke(*args: object) -> None:
        harness.boundary.external("revoke")

    monkeypatch.setattr(oauth, "exchange_oauth_code", exchange)
    monkeypatch.setattr(oauth, "list_user_installations", installations)
    monkeypatch.setattr(oauth, "revoke_oauth_token", revoke)
    state = create_agent_github_platform_oauth_state(
        "state-secret",
        effective_generation="generation-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        user_id="user-1",
        redirect_uri="https://app.test/oauth/github/callback",
        callback_target="agent_github_installations",
    )
    with pytest.raises(HTTPException if stage == "denied" else type(failure)) as raised:
        await oauth.get_agent_github_platform_installations(
            _member(WorkspaceUserRole.OWNER),
            toolkit_service,
            harness.service.config,
            harness.service.platform_runtime,
            oauth.GitHubPlatformInstallationsRequest(code="code", state=state),
            handle="workspace",
            agent_id="agent-1",
        )
    if stage == "denied":
        assert isinstance(raised.value, HTTPException)
        assert raised.value.status_code == 403
    else:
        assert raised.value is failure
    assert harness.boundary.calls[-1] == "revoke"
    assert not harness.boundary.active


async def test_workspace_revoke_cancellation_happens_after_completed_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation after success-only revoke starts cannot undo completed sync."""
    harness = _harness(SharedOAuthContext(None, None), Success(None))
    failure = asyncio.CancelledError()

    async def exchange(*args: object) -> str:
        harness.boundary.external("github-token")
        return "temporary-token"

    async def installations(*args: object) -> list[dict[str, object]]:
        harness.boundary.external("list")
        return []

    async def revoke(*args: object) -> None:
        harness.boundary.external("revoke")
        raise failure

    monkeypatch.setattr(service_module, "exchange_oauth_code", exchange)
    monkeypatch.setattr(service_module, "list_user_installations", installations)
    monkeypatch.setattr(service_module, "revoke_oauth_token", revoke)
    with pytest.raises(asyncio.CancelledError) as raised:
        await harness.service.platform_installations(
            user_id="user-1",
            session_id="session-1",
            workspace_id="workspace-1",
            code="code",
            state=create_platform_oauth_state(
                "state-secret", effective_generation="generation-1"
            ),
        )
    assert raised.value is failure
    assert harness.boundary.synced == [()]
    assert harness.boundary.calls[-2:] == ["sync:closed", "revoke"]
    assert not harness.boundary.active
