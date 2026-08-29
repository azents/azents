"""External conversation configuration tests."""

import pytest
from pydantic import ValidationError

from azents.core.config import (
    ExternalChannelConversationLockConfig,
    ExternalChannelGatewayLeaseConfig,
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
    assert settings.testenv_external_channel_gateway_lease_duration_seconds is None
    assert settings.testenv_external_channel_gateway_renewal_interval_seconds is None


def test_external_conversation_lock_renews_before_lease_expiry() -> None:
    with pytest.raises(ValidationError, match="renewal must be shorter"):
        ExternalChannelConversationLockConfig(
            backend=ExternalChannelConversationLockBackend.MEMORY,
            lease_ttl_seconds=10.0,
            renewal_interval_seconds=10.0,
        )


def test_external_channel_gateway_lease_renews_before_expiry() -> None:
    with pytest.raises(ValidationError, match="renewal must be shorter"):
        ExternalChannelGatewayLeaseConfig(
            duration_seconds=5.0,
            renewal_interval_seconds=5.0,
        )


@pytest.mark.parametrize(
    ("duration_seconds", "renewal_interval_seconds", "message"),
    [
        (2e-7, 1e-7, "at least one microsecond"),
        (1.4e-6, 1e-6, "renewal must be shorter"),
    ],
)
def test_external_channel_gateway_lease_validates_effective_timing(
    duration_seconds: float,
    renewal_interval_seconds: float,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        ExternalChannelGatewayLeaseConfig(
            duration_seconds=duration_seconds,
            renewal_interval_seconds=renewal_interval_seconds,
        )


def test_testenv_gateway_lease_settings_require_complete_timing() -> None:
    with pytest.raises(ValidationError, match="must be configured together"):
        Settings(
            rdb_host="localhost",
            rdb_user="azents",
            rdb_db_name="azents",
            auth_jwt_secret_key="test-secret",
            credential_encryption_key="test-key",
            testenv_external_channel_gateway_lease_duration_seconds=5.0,
        )
