"""Provider identity OAuth adapter contract tests."""

import traceback
from unittest.mock import patch

import httpx2
import pytest
from authlib.integrations.httpx_client import AsyncOAuth2Client
from slack_sdk.errors import SlackClientError

import azents.core.external_account_oauth as oauth
from azents.core.config import Config
from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_oauth import (
    DiscordIdentityOAuthAdapter,
    ExternalAccountOAuthProviderError,
    SlackIdentityOAuthAdapter,
    _discord_identity,
    _slack_identity,
)


def _testenv_config(*, enabled: bool) -> Config:
    """Build the minimal configuration needed for endpoint selection tests."""
    return Config.model_construct(
        testenv_api_enabled=enabled,
        testenv_slack_oauth_base_url="http://slack-fake:8083",
        testenv_discord_oauth_base_url="http://discord-fake:8085",
    )


def test_testenv_oauth_endpoint_overrides_require_the_testenv_gate() -> None:
    """Provider endpoints stay fixed unless testenv overrides are explicitly enabled."""
    disabled = _testenv_config(enabled=False)
    enabled = _testenv_config(enabled=True)

    slack_production = oauth.external_account_oauth_endpoints(
        ExternalChannelProvider.SLACK,
        disabled,
    )
    slack_testenv = oauth.external_account_oauth_endpoints(
        ExternalChannelProvider.SLACK,
        enabled,
    )
    discord_production = oauth.external_account_oauth_endpoints(
        ExternalChannelProvider.DISCORD,
        disabled,
    )
    discord_testenv = oauth.external_account_oauth_endpoints(
        ExternalChannelProvider.DISCORD,
        enabled,
    )

    assert slack_production.authorization_url == oauth.SLACK_IDENTITY_AUTHORIZE_URL
    assert slack_production.token_url == oauth.SLACK_IDENTITY_TOKEN_URL
    assert slack_production.userinfo_url == oauth.SLACK_IDENTITY_USERINFO_URL
    assert slack_testenv.authorization_url == ("http://slack-fake:8083/oauth/authorize")
    assert slack_testenv.token_url == (
        "http://slack-fake:8083/api/openid.connect.token"
    )
    assert slack_testenv.userinfo_url == (
        "http://slack-fake:8083/api/openid.connect.userInfo"
    )
    assert discord_production.authorization_url == oauth.DISCORD_IDENTITY_AUTHORIZE_URL
    assert discord_production.token_url == oauth.DISCORD_IDENTITY_TOKEN_URL
    assert discord_production.userinfo_url == oauth.DISCORD_IDENTITY_USERINFO_URL
    assert discord_testenv.authorization_url == (
        "http://discord-fake:8085/oauth2/authorize"
    )
    assert discord_testenv.token_url == "http://discord-fake:8085/api/oauth2/token"
    assert discord_testenv.userinfo_url == "http://discord-fake:8085/api/users/@me"


def test_slack_authorization_uses_identity_scopes() -> None:
    """Slack authorization requests only OpenID identity scopes."""
    url = SlackIdentityOAuthAdapter().authorization_url(
        client_id="slack-client",
        redirect_uri="https://azents.example/oauth/external-account/slack/callback",
        state="state",
        code_challenge=None,
    )

    assert "openid+profile" in url
    assert "client_id=slack-client" in url
    assert "state=state" in url


def test_discord_authorization_uses_identify_and_pkce() -> None:
    """Discord authorization requests identify and forwards the PKCE challenge."""
    url = DiscordIdentityOAuthAdapter().authorization_url(
        client_id="discord-client",
        redirect_uri="https://azents.example/oauth/external-account/discord/callback",
        state="state",
        code_challenge="challenge",
    )

    assert "scope=identify" in url
    assert "code_challenge=challenge" in url
    assert "code_challenge_method=S256" in url


@pytest.mark.asyncio
async def test_slack_adapter_decodes_sdk_response_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slack adapter consumes AsyncSlackResponse.data, not the wrapper object."""

    class FakeSlackResponse:
        def __init__(self, data: dict[str, object]) -> None:
            self.data = data

    class FakeSlackClient:
        def __init__(self, **_: object) -> None:
            pass

        async def openid_connect_token(self, **_: object) -> FakeSlackResponse:
            return FakeSlackResponse({"ok": True, "access_token": "token"})

        async def openid_connect_userInfo(self) -> FakeSlackResponse:
            return FakeSlackResponse(
                {
                    "sub": "U123",
                    "https://slack.com/team_id": "T123",
                    "https://slack.com/team_name": "Example Team",
                    "name": "Example User",
                }
            )

    monkeypatch.setattr(oauth, "AsyncWebClient", FakeSlackClient)
    identity = await SlackIdentityOAuthAdapter().exchange_identity(
        client_id="client",
        client_secret="secret",
        code="code",
        redirect_uri="https://azents.example/callback",
        code_verifier=None,
    )

    assert identity.provider is ExternalChannelProvider.SLACK
    assert identity.provider_user_id == "U123"


@pytest.mark.asyncio
async def test_discord_adapter_uses_client_token_for_user_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discord adapter uses Authlib's authenticated client request surface."""

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return {"id": "123456789", "global_name": "Example User"}

    class FakeDiscordClient:
        def __init__(self, **_: object) -> None:
            self.user_info_called = False

        def register_compliance_hook(self, *args: object) -> None:
            pass

        async def __aenter__(self) -> "FakeDiscordClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def fetch_token(self, *args: object, **kwargs: object) -> dict[str, str]:
            return {"access_token": "token"}

        async def get(self, url: str) -> FakeResponse:
            assert url == oauth.DISCORD_IDENTITY_USERINFO_URL
            self.user_info_called = True
            return FakeResponse()

    monkeypatch.setattr(oauth, "AsyncOAuth2Client", FakeDiscordClient)
    identity = await DiscordIdentityOAuthAdapter().exchange_identity(
        client_id="client",
        client_secret="secret",
        code="code",
        redirect_uri="https://azents.example/callback",
        code_verifier="verifier",
    )

    assert identity.provider is ExternalChannelProvider.DISCORD
    assert identity.provider_user_id == "123456789"


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["token", "userinfo"])
@pytest.mark.parametrize("status", [400, 429, 503])
async def test_discord_real_sdk_http_errors_are_sanitized(
    stage: str,
    status: int,
) -> None:
    """Native SDK HTTP failures retain the safe provider-rejection boundary."""
    requests: list[httpx2.Request] = []

    def provider(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if stage == "token" or request.url.path == "/api/users/@me":
            return httpx2.Response(status, text="provider-body-secret")
        return httpx2.Response(
            200, json={"access_token": "token", "token_type": "Bearer"}
        )

    client = AsyncOAuth2Client(
        client_id="client",
        client_secret="secret",
        scope="identify",
        token_endpoint_auth_method="client_secret_post",
        transport=httpx2.MockTransport(provider),
    )
    with patch.object(oauth, "AsyncOAuth2Client", return_value=client):
        with pytest.raises(
            ExternalAccountOAuthProviderError,
            match="discord_identity_exchange_failed",
        ) as caught:
            await DiscordIdentityOAuthAdapter().exchange_identity(
                client_id="client",
                client_secret="secret",
                code="code",
                redirect_uri="https://azents.example/callback",
                code_verifier="verifier",
            )
    assert len(requests) == (1 if stage == "token" else 2)
    assert client.is_closed
    assert "provider-body-secret" not in "".join(
        traceback.format_exception(caught.value)
    )
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [b"not-json", b"[]", b"null", b'"provider-body-secret"'],
)
async def test_discord_real_sdk_malformed_token_payload_is_sanitized(
    body: bytes,
) -> None:
    """Successful HTTP responses still require an object-shaped token payload."""
    client = AsyncOAuth2Client(
        client_id="client",
        client_secret="secret",
        scope="identify",
        token_endpoint_auth_method="client_secret_post",
        transport=httpx2.MockTransport(
            lambda request: httpx2.Response(200, content=body)
        ),
    )
    with patch.object(oauth, "AsyncOAuth2Client", return_value=client):
        with pytest.raises(
            ExternalAccountOAuthProviderError,
            match="discord_token_response_invalid",
        ) as caught:
            await DiscordIdentityOAuthAdapter().exchange_identity(
                client_id="client",
                client_secret="secret",
                code="code",
                redirect_uri="https://azents.example/callback",
                code_verifier="verifier",
            )
    assert client.is_closed
    assert "provider-body-secret" not in "".join(
        traceback.format_exception(caught.value)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({}, "discord_token_missing"),
        ({"error": "invalid_grant"}, "discord_identity_exchange_failed"),
    ],
)
async def test_discord_real_sdk_invalid_token_objects(
    payload: dict[str, str],
    error: str,
) -> None:
    """Object-shaped responses still require an accepted access token."""
    client = AsyncOAuth2Client(
        client_id="client",
        client_secret="secret",
        token_endpoint_auth_method="client_secret_post",
        transport=httpx2.MockTransport(
            lambda request: httpx2.Response(200, json=payload)
        ),
    )
    with patch.object(oauth, "AsyncOAuth2Client", return_value=client):
        with pytest.raises(ExternalAccountOAuthProviderError, match=error):
            await DiscordIdentityOAuthAdapter().exchange_identity(
                client_id="client",
                client_secret="secret",
                code="code",
                redirect_uri="https://azents.example/callback",
                code_verifier="verifier",
            )
    assert client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [RuntimeError("unexpected defect"), TypeError("invalid collaborator")]
)
async def test_discord_sdk_programming_errors_remain_observable(
    failure: Exception,
) -> None:
    """Expected provider decoding does not swallow arbitrary SDK defects."""

    def provider(request: httpx2.Request) -> httpx2.Response:
        raise failure

    client = AsyncOAuth2Client(
        client_id="client",
        transport=httpx2.MockTransport(provider),
    )
    with patch.object(oauth, "AsyncOAuth2Client", return_value=client):
        with pytest.raises(type(failure)) as caught:
            await DiscordIdentityOAuthAdapter().exchange_identity(
                client_id="client",
                client_secret="secret",
                code="code",
                redirect_uri="https://azents.example/callback",
                code_verifier="verifier",
            )
    assert caught.value is failure
    assert client.is_closed


@pytest.mark.asyncio
async def test_provider_exception_traceback_does_not_retain_raw_secret(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Expected SDK failures render a sanitized traceback without provider material."""

    class FailingSlackClient:
        def __init__(self, **_: object) -> None:
            pass

        async def openid_connect_token(self, **_: object) -> object:
            raise SlackClientError("provider-body-secret")

    monkeypatch.setattr(oauth, "AsyncWebClient", FailingSlackClient)
    with pytest.raises(
        ExternalAccountOAuthProviderError,
        match="slack_identity_exchange_failed",
    ) as caught:
        await SlackIdentityOAuthAdapter().exchange_identity(
            client_id="client",
            client_secret="secret",
            code="code",
            redirect_uri="https://azents.example/callback",
            code_verifier=None,
        )
    rendered = "".join(traceback.format_exception(caught.value))
    assert "slack_identity_exchange_failed" in rendered
    assert "provider-body-secret" not in rendered
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    assert "provider-body-secret" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [RuntimeError("unexpected defect"), TypeError("invalid collaborator")]
)
async def test_unexpected_adapter_errors_remain_observable(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    """Programming failures propagate unchanged rather than as provider rejection."""

    class DefectiveSlackClient:
        def __init__(self, **_: object) -> None:
            pass

        async def openid_connect_token(self, **_: object) -> object:
            raise failure

    monkeypatch.setattr(oauth, "AsyncWebClient", DefectiveSlackClient)
    with pytest.raises(type(failure)) as caught:
        await SlackIdentityOAuthAdapter().exchange_identity(
            client_id="client",
            client_secret="secret",
            code="code",
            redirect_uri="https://azents.example/callback",
            code_verifier=None,
        )
    assert caught.value is failure
    assert not isinstance(caught.value, ExternalAccountOAuthProviderError)
    assert str(failure) in "".join(traceback.format_exception(caught.value))


def test_slack_identity_keeps_team_scope() -> None:
    """Slack identity ownership is scoped by team and user ID."""
    identity = _slack_identity(
        {
            "sub": "U123",
            "https://slack.com/team_id": "T123",
            "https://slack.com/team_name": "Example Team",
            "name": "Example User",
        }
    )

    assert identity.provider is ExternalChannelProvider.SLACK
    assert identity.identity_scope == "T123"
    assert identity.provider_user_id == "U123"
    assert identity.provider_tenant_display_label == "Example Team"


def test_discord_identity_is_provider_global() -> None:
    """Discord identity ownership does not depend on a Guild."""
    identity = _discord_identity({"id": "123456789", "global_name": "Example User"})

    assert identity.provider is ExternalChannelProvider.DISCORD
    assert identity.identity_scope == "global"
    assert identity.provider_user_id == "123456789"


@pytest.mark.parametrize("payload", [None, {}, {"id": "not-a-snowflake"}])
def test_malformed_discord_identity_is_rejected(payload: object) -> None:
    """Malformed provider payloads fail before link persistence."""
    with pytest.raises(ExternalAccountOAuthProviderError):
        _discord_identity(payload)
