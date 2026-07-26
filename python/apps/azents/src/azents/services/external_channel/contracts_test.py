"""External Channel provider contract tests."""

import datetime

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import (
    DiscordConnectionCredentials,
    ExternalChannelCapabilitySnapshot,
    ExternalChannelConnectionCredentialPayload,
    ExternalChannelConnectionStatusSnapshot,
    ExternalChannelProviderIdentity,
    SlackConnectionCredentials,
)
from azents.services.external_channel.provider import (
    DiscordExternalChannelProviderContract,
    SlackExternalChannelProviderContract,
)


def _credentials(*, app_token: str | None) -> SlackConnectionCredentials:
    """Return valid Slack credentials for one contract test."""
    return SlackConnectionCredentials(
        bot_token="xoxb-test",
        signing_secret="signing-secret",
        app_token=app_token,
    )


def test_socket_mode_credentials_require_an_app_token() -> None:
    with pytest.raises(ValidationError, match="requires an app token"):
        ExternalChannelConnectionCredentialPayload(
            provider=ExternalChannelProvider.SLACK,
            transport=ExternalChannelTransport.SOCKET,
            ingress_profile=ExternalChannelIngressProfile.SLACK_SOCKET,
            credentials=_credentials(app_token=None),
        )


def test_credential_payload_rejects_blank_secret() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        SlackConnectionCredentials(
            bot_token=" ",
            signing_secret="signing-secret",
            app_token=None,
        )


def test_credentials_are_encrypted_and_snapshot_is_redacted() -> None:
    credentials = _credentials(app_token="xapp-test")
    codec = ExternalChannelCredentialsCodec(
        cipher=CredentialCipher(Fernet.generate_key().decode())
    )

    encrypted = codec.encrypt(credentials)
    decrypted = codec.decrypt(encrypted)
    snapshot = codec.snapshot(credentials)

    assert encrypted != credentials.bot_token
    assert decrypted == credentials
    assert snapshot.model_dump() == {
        "provider": ExternalChannelProvider.SLACK,
        "configured_fields": ("bot_token", "signing_secret", "app_token"),
    }
    assert credentials.bot_token not in snapshot.model_dump_json()
    assert credentials.signing_secret not in snapshot.model_dump_json()
    assert credentials.app_token is not None
    assert credentials.app_token not in snapshot.model_dump_json()


def test_status_snapshot_contains_only_redacted_connection_state() -> None:
    credentials = _credentials(app_token=None)
    snapshot = ExternalChannelConnectionStatusSnapshot(
        status=ExternalChannelConnectionStatus.ACTIVE,
        code="verified",
        message="Connection verified.",
        action_hint=None,
        checked_at=datetime.datetime(2026, 7, 21, tzinfo=datetime.UTC),
        identity=ExternalChannelProviderIdentity(
            provider=ExternalChannelProvider.SLACK,
            app_id="A123",
            tenant_id="T123",
            bot_user_id="U123",
        ),
        credentials=ExternalChannelCredentialsCodec.snapshot(credentials),
        capabilities=ExternalChannelCapabilitySnapshot(
            provider=ExternalChannelProvider.SLACK,
            transport=ExternalChannelTransport.HTTP,
            inbound_events=True,
            thread_history=True,
            post_messages=True,
            update_messages=True,
            delete_messages=True,
            download_files=True,
            upload_files=False,
        ),
    )

    serialized = snapshot.model_dump_json()

    assert snapshot.status is ExternalChannelConnectionStatus.ACTIVE
    assert "xoxb-test" not in serialized
    assert "signing-secret" not in serialized


def test_slack_contract_accepts_only_slack_credentials() -> None:
    payload = ExternalChannelConnectionCredentialPayload(
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
        credentials=_credentials(app_token=None),
    )

    result = SlackExternalChannelProviderContract().validate_connection_credentials(
        payload
    )

    assert result == payload.credentials


def test_discord_contract_requires_gateway_http_ingress_profile() -> None:
    credentials = DiscordConnectionCredentials(bot_token="discord-bot-token")

    with pytest.raises(ValidationError, match="requires the Gateway and HTTP"):
        ExternalChannelConnectionCredentialPayload(
            provider=ExternalChannelProvider.DISCORD,
            transport=ExternalChannelTransport.HTTP,
            ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
            credentials=credentials,
        )

    payload = ExternalChannelConnectionCredentialPayload(
        provider=ExternalChannelProvider.DISCORD,
        transport=ExternalChannelTransport.HTTP,
        ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
        credentials=credentials,
    )

    result = DiscordExternalChannelProviderContract().validate_connection_credentials(
        payload
    )

    assert result == credentials


def test_discord_credentials_are_encrypted_and_redacted() -> None:
    credentials = DiscordConnectionCredentials(bot_token="discord-bot-token")
    codec = ExternalChannelCredentialsCodec(
        cipher=CredentialCipher(Fernet.generate_key().decode())
    )

    encrypted = codec.encrypt(credentials)
    decrypted = codec.decrypt(encrypted)
    snapshot = codec.snapshot(credentials)

    assert encrypted != credentials.bot_token
    assert decrypted == credentials
    assert snapshot.model_dump() == {
        "provider": ExternalChannelProvider.DISCORD,
        "configured_fields": ("bot_token",),
    }
    assert credentials.bot_token not in snapshot.model_dump_json()
