"""Provider identity OAuth adapter contract tests."""

import traceback

import pytest

import azents.core.external_account_oauth as oauth
from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_oauth import (
    DiscordIdentityOAuthAdapter,
    ExternalAccountOAuthProviderError,
    SlackIdentityOAuthAdapter,
    _discord_identity,
    _slack_identity,
)


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
async def test_provider_exception_traceback_does_not_retain_raw_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanitized adapter errors do not chain provider response material."""

    class FailingSlackClient:
        def __init__(self, **_: object) -> None:
            pass

        async def openid_connect_token(self, **_: object) -> object:
            raise RuntimeError("provider-body-secret")

    monkeypatch.setattr(oauth, "AsyncWebClient", FailingSlackClient)
    with pytest.raises(
        ExternalAccountOAuthProviderError,
        match="slack_identity_exchange_failed",
    ):
        await SlackIdentityOAuthAdapter().exchange_identity(
            client_id="client",
            client_secret="secret",
            code="code",
            redirect_uri="https://azents.example/callback",
            code_verifier=None,
        )
    assert "provider-body-secret" not in traceback.format_exc()


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
