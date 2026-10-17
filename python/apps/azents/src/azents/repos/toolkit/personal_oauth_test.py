"""Personal MCP callback authority and stale-publication tests against PostgreSQL."""

import asyncio
import dataclasses
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest

from azents.core.config import Config, CredentialEncryptionConfig
from azents.core.mcp_discovery import DcrRegistrationResult, OAuthServerMetadata
from azents.core.oauth2 import (
    OAuthTokenResponse,
    create_toolkit_oauth_state,
    verify_personal_toolkit_oauth_state,
    verify_toolkit_oauth_state,
)
from azents.core.personal_toolkit import (
    PersonalToolkitConfigurationConflict,
    PersonalToolkitNotFound,
)
from azents.core.tools import TestConnectionResult as ConnectionResult
from azents.engine.tools.mcp import McpToolkitProvider
from azents.repos.toolkit.data import ToolkitCreation
from azents.repos.toolkit.personal_management_test import Harness
from azents.repos.toolkit.personal_management_test import (
    fixture as fixture,  # noqa: PLC0414 -- register its shared PostgreSQL foundation
)
from azents.repos.toolkit.personal_management_test import (
    harness as harness,  # noqa: PLC0414 -- register the actual management fixture
)
from azents.services.toolkit_oauth import helpers
from azents.services.toolkit_oauth.data import (
    ToolkitConnectionTestInput,
    ToolkitOAuthError,
)
from azents.services.toolkit_oauth.personal import PersonalToolkitOAuthService


@dataclasses.dataclass(frozen=True)
class OAuthHarness:
    management: Harness
    service: PersonalToolkitOAuthService
    toolkit_id: str
    discover: AsyncMock
    register: AsyncMock
    exchange: AsyncMock


async def test_personal_connection_tests_use_common_provider_and_exact_saved_owner(
    oauth: OAuthHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    o = oauth
    provider_test = AsyncMock(
        return_value=ConnectionResult(
            success=True,
            message="fixture-ok",
            discovered_auth_url=None,
            discovered_token_url=None,
            supports_dcr=None,
        )
    )
    monkeypatch.setattr(o.service.registry["mcp"], "test_connection", provider_test)
    saved = await o.service.test_saved(o.management.subject, o.toolkit_id)
    assert saved.success
    assert provider_test.await_args is not None
    validated, credentials = provider_test.await_args.args
    assert validated.server_url == "https://mcp.test" and credentials is None
    with pytest.raises(PersonalToolkitNotFound):
        await o.service.test_saved(o.management.other, o.toolkit_id)
    assert provider_test.await_count == 1
    draft = ToolkitConnectionTestInput(
        toolkit_type="mcp",
        config={"server_url": "https://draft.test", "auth_type": "bearer"},
        credentials={"type": "bearer", "token": "fixture-draft-only"},
        toolkit_config_id=None,
    )
    assert (await o.service.test_unsaved(o.management.subject, draft)).success
    current = await o.management.repository.get(o.management.subject, o.toolkit_id)
    assert current.toolkit.config["server_url"] == "https://mcp.test"
    assert current.toolkit.credentials is None


async def test_personal_connection_test_rechecks_after_platform_preparation(
    oauth: OAuthHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    o = oauth
    provider_test = AsyncMock(
        return_value=ConnectionResult(
            success=True,
            message="fixture-ok",
            discovered_auth_url=None,
            discovered_token_url=None,
            supports_dcr=None,
        )
    )
    monkeypatch.setattr(o.service.registry["mcp"], "test_connection", provider_test)

    async def change(*args: object) -> helpers.PreparedPlatformTestCredentials:
        del args
        await o.management.foundation.operations.update(
            user_id=o.management.subject.user_id,
            workspace_id=o.management.subject.workspace_id,
            toolkit_id=o.toolkit_id,
            update={"name": "Concurrent"},
        )
        return helpers.PreparedPlatformTestCredentials(None, None)

    monkeypatch.setattr(helpers, "prepare_platform_app_test_credentials", change)
    with pytest.raises(PersonalToolkitConfigurationConflict):
        await o.service.test_saved(o.management.subject, o.toolkit_id)
    provider_test.assert_not_awaited()


@pytest.fixture
async def oauth(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> OAuthHarness:
    """Use real persistence and fake only the Provider I/O boundaries."""
    h = harness
    toolkit = await h.repository.create(
        h.subject,
        ToolkitCreation(
            toolkit_type="mcp",
            slug="oauth",
            name="OAuth",
            config={
                "server_url": "https://mcp.test",
                "auth_type": "oauth2",
                "scopes": ["read"],
            },
            credentials=None,
            always_expose_tools=True,
        ),
        platform_authority=None,
    )
    discover = AsyncMock(
        return_value=OAuthServerMetadata(
            authorization_endpoint="https://provider.test/authorize",
            token_endpoint="https://provider.test/token",
            registration_endpoint="https://provider.test/register",
            scopes_supported=["read"],
            issuer="https://provider.test",
        )
    )
    register = AsyncMock(
        return_value=DcrRegistrationResult(
            client_id="fixture-client", client_secret="fixture-client-secret"
        )
    )
    exchange = AsyncMock(
        return_value=OAuthTokenResponse(
            access_token="fixture-access",
            refresh_token="fixture-refresh",
            token_type="Bearer",
        )
    )
    monkeypatch.setattr(helpers, "discover_required_metadata", discover)
    monkeypatch.setattr(helpers, "register_client", register)
    monkeypatch.setattr(helpers, "exchange_and_handle_errors", exchange)
    service = PersonalToolkitOAuthService(
        repository=h.repository,
        config=Config.model_construct(
            web_url="https://app.test",
            mcp_proxy_url=None,
            credential_encryption=CredentialEncryptionConfig(key="fixture-state-key"),
        ),
        registry={"mcp": McpToolkitProvider()},
        platform_runtime=MagicMock(),
    )
    return OAuthHarness(h, service, toolkit.toolkit.id, discover, register, exchange)


def state_from(url: str) -> str:
    return parse_qs(urlsplit(url).query)["state"][0]


async def test_connect_exchange_owner_bound_and_replay_denied(
    oauth: OAuthHarness,
) -> None:
    """Reuse common DCR/PKCE and reject consumed setup before another exchange."""
    o = oauth
    subject = o.management.subject
    url = await o.service.connect(subject, o.toolkit_id)
    params = parse_qs(urlsplit(url).query)
    assert params["client_id"] == ["fixture-client"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["resource"] == ["https://mcp.test"]
    assert "handle=" in params["redirect_uri"][0]
    state = state_from(url)
    payload = verify_personal_toolkit_oauth_state(state, "fixture-state-key")
    assert payload is not None and payload.owner.user_id == subject.user_id
    assert payload.auth_session_id == subject.session_id
    assert verify_toolkit_oauth_state(state, "fixture-state-key") is None
    await o.service.exchange(subject, o.toolkit_id, code="fixture-code", state=state)
    current = await o.management.repository.read_oauth_context(subject, o.toolkit_id)
    assert (
        current.connection is not None
        and current.connection.access_token == "fixture-access"
    )
    assert current.connection.refresh_token == "fixture-refresh"
    o.exchange.assert_awaited_once()
    assert o.exchange.await_args is not None
    assert o.exchange.await_args.kwargs["code_verifier"] == payload.code_verifier
    with pytest.raises(PersonalToolkitConfigurationConflict):
        await o.service.exchange(
            subject, o.toolkit_id, code="fixture-code", state=state
        )
    assert o.exchange.await_count == 1
    # Reconnect retains the client and current credential until new publication.
    await o.service.connect(subject, o.toolkit_id)
    assert o.register.await_count == 1
    retained = await o.management.repository.read_oauth_context(subject, o.toolkit_id)
    assert (
        retained.connection is not None
        and retained.connection.access_token == "fixture-access"
    )


@pytest.mark.parametrize(
    "wrong", ["owner", "workspace", "session", "target", "shared_state"]
)
async def test_callback_cannot_swap_owner_session_or_target(
    oauth: OAuthHarness, wrong: str
) -> None:
    """No token endpoint call happens for a foreign callback binding."""
    o = oauth
    url = await o.service.connect(o.management.subject, o.toolkit_id)
    state = state_from(url)
    subject = o.management.subject
    toolkit_id = o.toolkit_id
    if wrong == "owner":
        subject = o.management.other
    elif wrong == "workspace":
        subject = dataclasses.replace(
            subject, workspace_id=o.management.foundation.workspace_ids[1]
        )
    elif wrong == "session":
        subject = dataclasses.replace(subject, session_id=o.management.other.session_id)
    elif wrong == "target":
        toolkit_id = "foreign-toolkit"
    else:
        state = create_toolkit_oauth_state(
            toolkit_id=o.toolkit_id,
            workspace_id=o.management.foundation.workspace_ids[0],
            user_id=subject.user_id,
            redirect_uri="https://app.test/callback",
            code_verifier="fixture-verifier",
            secret_key="fixture-state-key",
        )
    with pytest.raises(ToolkitOAuthError):
        await o.service.exchange(subject, toolkit_id, code="fixture-code", state=state)
    o.exchange.assert_not_awaited()


async def test_source_changed_during_discovery_prevents_setup_publication(
    oauth: OAuthHarness,
) -> None:
    """Discovery runs outside DB scope and cannot overwrite a concurrent config edit."""
    o = oauth

    async def discovered(*args: object, **kwargs: object) -> OAuthServerMetadata:
        del args, kwargs
        await o.management.foundation.operations.update(
            user_id=o.management.subject.user_id,
            workspace_id=o.management.subject.workspace_id,
            toolkit_id=o.toolkit_id,
            update={"name": "Concurrent"},
        )
        return o.discover.return_value

    o.discover.side_effect = discovered
    with pytest.raises(PersonalToolkitConfigurationConflict):
        await o.service.connect(o.management.subject, o.toolkit_id)
    current = await o.management.repository.read_oauth_context(
        o.management.subject, o.toolkit_id
    )
    assert current.connection is None and current.toolkit.name == "Concurrent"


async def test_disconnect_during_token_exchange_blocks_late_publication(
    oauth: OAuthHarness,
) -> None:
    """An admitted exchange can return but cannot publish after disconnect."""
    o = oauth
    subject = o.management.subject
    state = state_from(await o.service.connect(subject, o.toolkit_id))
    started = asyncio.Event()
    release = asyncio.Event()
    receipt = o.exchange.return_value

    async def exchange(**kwargs: object) -> OAuthTokenResponse:
        del kwargs
        started.set()
        await release.wait()
        return receipt

    o.exchange.side_effect = exchange
    task = asyncio.create_task(
        o.service.exchange(subject, o.toolkit_id, code="fixture-code", state=state)
    )
    try:
        async with asyncio.timeout(10):
            await started.wait()
            await o.service.disconnect(subject, o.toolkit_id)
            release.set()
            with pytest.raises(PersonalToolkitConfigurationConflict):
                await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    current = await o.management.repository.read_oauth_context(subject, o.toolkit_id)
    assert current.connection is None
