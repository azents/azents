"""Listener-free validation of interpreted Discord fixture response contracts."""

import pytest
from pydantic import ValidationError

from support.discord_fake_observations import (
    DiscordCommandIdentity,
    DiscordDeliveryBarrier,
    DiscordOAuthToken,
)


def test_provider_identity_preserves_opaque_string_and_extension_compatibility() -> (
    None
):
    """Provider command extensions do not alter the opaque operation identity."""
    identity = DiscordCommandIdentity.model_validate_json(
        '{"id":"000000000000000001","name":"provider extension","options":[]}'
    )
    assert identity.id == "000000000000000001"


@pytest.mark.parametrize("payload", ["{}", '{"id":null}', '{"id":123}', '{"id":""}'])
def test_provider_command_identity_rejects_missing_null_or_coerced_ids(
    payload: str,
) -> None:
    """An ID used in another request must be a non-empty string at ingress."""
    with pytest.raises(ValidationError):
        DiscordCommandIdentity.model_validate_json(payload)


def test_oauth_token_is_typed_without_credentials_in_model_repr() -> None:
    """OAuth provider extensions remain outside the interpreted token field."""
    token = DiscordOAuthToken.model_validate_json(
        '{"access_token":"private-token","token_type":"Bearer","scope":"identify"}'
    )
    assert token.access_token == "private-token"
    assert "private-token" not in repr(token)


@pytest.mark.parametrize(
    "payload", ["{}", '{"access_token":null}', '{"access_token":123}']
)
def test_oauth_token_rejects_malformed_response_with_safe_error(payload: str) -> None:
    """Failed provider token decoding never includes input values in messages."""
    with pytest.raises(ValidationError) as caught:
        DiscordOAuthToken.model_validate_json(payload)
    assert "input_value" not in str(caught.value)


def test_barrier_unset_operation_and_boolean_state() -> None:
    """The producer's explicit null operation is valid before configuration."""
    barrier = DiscordDeliveryBarrier.model_validate_json(
        '{"operation":null,"occurrence":1,"request_count":0,"reached":false,"released":false}'
    )
    assert barrier.operation is None
    assert barrier.reached is False
    assert "operation" in barrier.model_fields_set


@pytest.mark.parametrize(
    "payload",
    [
        '{"occurrence":1,"request_count":0,"reached":false,"released":false}',
        '{"operation":null,"occurrence":1,"request_count":0,"reached":1,"released":false}',
        '{"operation":null,"occurrence":1,"request_count":"0","reached":false,"released":false}',
        '{"operation":null,"occurrence":1,"request_count":0,"reached":false,"released":false,"extra":"secret"}',
    ],
)
def test_private_barrier_rejects_missing_coerced_or_unknown_fields(
    payload: str,
) -> None:
    """The private control protocol rejects wire changes instead of defaulting."""
    with pytest.raises(ValidationError) as caught:
        DiscordDeliveryBarrier.model_validate_json(payload)
    assert "input_value" not in str(caught.value)
    assert "secret" not in str(caught.value)
