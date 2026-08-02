"""External conversation configuration tests."""

import pytest
from pydantic import ValidationError

from azents.core.config import (
    ExternalChannelConversationLockConfig,
    Settings,
)
from azents.core.enums import ExternalChannelConversationLockBackend


def test_external_conversation_settings_default_to_redis_and_active_ingress() -> None:
    settings = Settings(
        rdb_host="localhost",
        rdb_user="azents",
        rdb_db_name="azents",
        auth_jwt_secret_key="test-secret",
        credential_encryption_key="test-key",
    )

    assert (
        settings.external_channel_conversation_lock_backend
        is ExternalChannelConversationLockBackend.REDIS
    )
    assert settings.external_channel_slack_http_message_ingress_quiesced is False
    assert settings.external_channel_slack_socket_message_ingress_quiesced is False
    assert settings.external_channel_discord_gateway_message_ingress_quiesced is False
    assert settings.external_channel_participation_enabled is False


def test_external_conversation_lock_renews_before_lease_expiry() -> None:
    with pytest.raises(ValidationError, match="renewal must be shorter"):
        ExternalChannelConversationLockConfig(
            backend=ExternalChannelConversationLockBackend.MEMORY,
            lease_ttl_seconds=10.0,
            renewal_interval_seconds=10.0,
        )
