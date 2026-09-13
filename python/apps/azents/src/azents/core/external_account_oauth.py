"""Provider identity OAuth contracts and adapters."""

import datetime
import logging
from dataclasses import dataclass
from typing import Protocol

from authlib.integrations.httpx_client import AsyncOAuth2Client
from slack_sdk.web.async_client import AsyncWebClient

from azents.core.enums import ExternalChannelProvider
from azents.core.oauth2 import build_authorization_url

EXTERNAL_ACCOUNT_OAUTH_ATTEMPT_TTL = datetime.timedelta(minutes=10)
EXTERNAL_ACCOUNT_OAUTH_RETENTION = datetime.timedelta(hours=24)
SLACK_IDENTITY_AUTHORIZE_URL = "https://slack.com/openid/connect/authorize"
SLACK_IDENTITY_TOKEN_URL = "https://slack.com/api/openid.connect.token"
SLACK_IDENTITY_USERINFO_URL = "https://slack.com/api/openid.connect.userInfo"
DISCORD_IDENTITY_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_IDENTITY_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_IDENTITY_USERINFO_URL = "https://discord.com/api/users/@me"

_SDK_LOGGER = logging.getLogger("azents.external_account_oauth.sdk")
_SDK_LOGGER.disabled = True


@dataclass(frozen=True)
class ExternalAccountOAuthIdentity:
    """Typed stable provider identity returned by OAuth."""

    provider: ExternalChannelProvider
    identity_scope: str
    provider_user_id: str
    provider_tenant_id: str | None
    provider_tenant_display_label: str | None
    provider_display_label: str


@dataclass(frozen=True)
class ExternalAccountOAuthClientConfiguration:
    """Provider client values resolved from Admin System Settings."""

    provider: ExternalChannelProvider
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class ExternalAccountOAuthCallbackContext:
    """Callback identity needed to classify and claim an OAuth attempt."""

    setting_generation: str
    redirect_uri: str


@dataclass(frozen=True)
class ExternalAccountOAuthRuntimeConfiguration:
    """Ready provider configuration for one authenticated OAuth operation."""

    client: ExternalAccountOAuthClientConfiguration
    setting_generation: str
    redirect_uri: str


class ExternalAccountOAuthProviderError(Exception):
    """Sanitized provider OAuth failure."""


class ExternalAccountOAuthAdapter(Protocol):
    """Provider-specific OAuth identity adapter contract."""

    provider: ExternalChannelProvider

    def authorization_url(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str | None,
    ) -> str:
        """Build one fixed-provider authorization URL."""
        ...

    async def exchange_identity(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
        code_verifier: str | None,
    ) -> ExternalAccountOAuthIdentity:
        """Exchange one code and return only a typed identity."""
        ...


class SlackIdentityOAuthAdapter:
    """Slack Sign in with Slack OpenID adapter."""

    provider = ExternalChannelProvider.SLACK

    def authorization_url(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str | None,
    ) -> str:
        """Build Slack's OpenID authorization URL."""
        del code_challenge
        return build_authorization_url(
            auth_url=SLACK_IDENTITY_AUTHORIZE_URL,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=["openid", "profile"],
            state=state,
        )

    async def exchange_identity(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
        code_verifier: str | None,
    ) -> ExternalAccountOAuthIdentity:
        """Exchange Slack code through the official Slack SDK."""
        del code_verifier
        try:
            client = AsyncWebClient(
                logger=_SDK_LOGGER,
                retry_handlers=[],
                timeout=20,
            )
            token_response = await client.openid_connect_token(
                client_id=client_id,
                client_secret=client_secret,
                code=code,
                redirect_uri=redirect_uri,
            )
            token_payload = _object_payload(token_response.data)
            if token_payload is None or token_payload.get("ok") is not True:
                raise ExternalAccountOAuthProviderError("slack_token_exchange_failed")
            access_token = token_payload.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise ExternalAccountOAuthProviderError("slack_token_missing")
            user_response = await AsyncWebClient(
                token=access_token,
                logger=_SDK_LOGGER,
                retry_handlers=[],
                timeout=20,
            ).openid_connect_userInfo()
            return _slack_identity(user_response.data)
        except ExternalAccountOAuthProviderError:
            raise
        except Exception:
            raise ExternalAccountOAuthProviderError(
                "slack_identity_exchange_failed"
            ) from None


class DiscordIdentityOAuthAdapter:
    """Discord authorization-code identity adapter."""

    provider = ExternalChannelProvider.DISCORD

    def authorization_url(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str | None,
    ) -> str:
        """Build Discord's identify authorization URL."""
        return build_authorization_url(
            auth_url=DISCORD_IDENTITY_AUTHORIZE_URL,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=["identify"],
            state=state,
            code_challenge=code_challenge,
        )

    async def exchange_identity(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
        code_verifier: str | None,
    ) -> ExternalAccountOAuthIdentity:
        """Exchange Discord code through Authlib and load `/users/@me`."""
        try:
            async with AsyncOAuth2Client(
                client_id=client_id,
                client_secret=client_secret,
                scope="identify",
            ) as client:
                token = await client.fetch_token(
                    DISCORD_IDENTITY_TOKEN_URL,
                    code=code,
                    redirect_uri=redirect_uri,
                    code_verifier=code_verifier,
                )
                access_token = token.get("access_token")
                if not isinstance(access_token, str) or not access_token:
                    raise ExternalAccountOAuthProviderError("discord_token_missing")
                response = await client.get(DISCORD_IDENTITY_USERINFO_URL)
                response.raise_for_status()
                payload = response.json()
            return _discord_identity(payload)
        except ExternalAccountOAuthProviderError:
            raise
        except Exception:
            raise ExternalAccountOAuthProviderError(
                "discord_identity_exchange_failed"
            ) from None


def _slack_identity(payload: object) -> ExternalAccountOAuthIdentity:
    """Decode the bounded Slack OpenID user-info payload."""
    values = _object_payload(payload)
    if values is None:
        raise ExternalAccountOAuthProviderError("slack_identity_malformed")
    user_id = values.get("sub")
    team_id = values.get("https://slack.com/team_id")
    team_name = values.get("https://slack.com/team_name")
    display_name = values.get("name") or values.get("preferred_username")
    if not isinstance(user_id, str) or not user_id:
        raise ExternalAccountOAuthProviderError("slack_identity_malformed")
    if not isinstance(team_id, str) or not team_id:
        raise ExternalAccountOAuthProviderError("slack_identity_malformed")
    return ExternalAccountOAuthIdentity(
        provider=ExternalChannelProvider.SLACK,
        identity_scope=team_id,
        provider_user_id=user_id,
        provider_tenant_id=team_id,
        provider_tenant_display_label=(
            team_name if isinstance(team_name, str) else None
        ),
        provider_display_label=(
            display_name
            if isinstance(display_name, str) and display_name
            else "Slack user"
        ),
    )


def _discord_identity(payload: object) -> ExternalAccountOAuthIdentity:
    """Decode the bounded Discord current-user payload."""
    values = _object_payload(payload)
    if values is None:
        raise ExternalAccountOAuthProviderError("discord_identity_malformed")
    user_id = values.get("id")
    display_name = values.get("global_name") or values.get("username")
    if not isinstance(user_id, str) or not user_id.isdigit():
        raise ExternalAccountOAuthProviderError("discord_identity_malformed")
    return ExternalAccountOAuthIdentity(
        provider=ExternalChannelProvider.DISCORD,
        identity_scope="global",
        provider_user_id=user_id,
        provider_tenant_id=None,
        provider_tenant_display_label=None,
        provider_display_label=(
            display_name
            if isinstance(display_name, str) and display_name
            else "Discord user"
        ),
    )


def _object_payload(value: object) -> dict[str, object] | None:
    """Return a JSON object with string keys, or None."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return value
