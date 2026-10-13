"""Provider evidence cannot prolong tokens while later identity checks complete."""

from azents.services.google_oauth.provider import GoogleTokenResponse


def test_conversion_retains_receipt_time_and_provider_cannot_override_it() -> None:
    receipt = GoogleTokenResponse.model_validate(
        {
            "access_token": "test-token",
            "expires_in": 300,
            "_received_at": "2099-01-01T00:00:00Z",
        }
    )
    first = receipt.tokens()
    second = receipt.tokens()
    assert first.expires_at == second.expires_at
    assert first.expires_at.year != 2099
