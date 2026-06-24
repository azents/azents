"""oauth2 utility tests."""

import pytest
from pydantic import ValidationError

from azents.core.oauth2 import (
    OAuthTokenError,
    OAuthTokenResponse,
    create_oauth_state,
    create_platform_oauth_state,
    parse_token_response,
    verify_oauth_state,
    verify_platform_oauth_state,
)


class TestOAuthTokenResponse:
    """OAuthTokenResponse Pydantic model tests."""

    def test_minimal(self) -> None:
        """Create with access_token only."""
        resp = OAuthTokenResponse.model_validate({"access_token": "tok"})
        assert resp.access_token == "tok"
        assert resp.refresh_token is None
        assert resp.expires_in is None
        assert resp.expires_at is None
        assert resp.token_type == "Bearer"

    def test_expires_in_to_expires_at(self) -> None:
        """Convert to expires_at when expires_in exists."""
        resp = OAuthTokenResponse.model_validate(
            {"access_token": "tok", "expires_in": 3600}
        )
        assert resp.expires_at is not None
        assert resp.expires_in == 3600

    def test_extra_fields_ignored(self) -> None:
        """Ignore unknown fields."""
        resp = OAuthTokenResponse.model_validate(
            {"access_token": "tok", "ok": True, "team": "T123"}
        )
        assert resp.access_token == "tok"

    def test_missing_access_token(self) -> None:
        """Raise ValidationError when access_token is missing."""
        with pytest.raises(ValidationError):
            OAuthTokenResponse.model_validate({"refresh_token": "ref"})


class TestParseTokenResponse:
    """_parse_token_response tests."""

    def test_success(self) -> None:
        """Parse normal token response."""
        result = parse_token_response(
            {"access_token": "tok", "refresh_token": "ref", "expires_in": 3600}
        )
        assert result.access_token == "tok"
        assert result.refresh_token == "ref"

    def test_error_rfc6749(self) -> None:
        """Detect RFC 6749 error response."""
        with pytest.raises(OAuthTokenError, match="invalid_grant"):
            parse_token_response(
                {"error": "invalid_grant", "error_description": "Code expired"}
            )

    def test_error_nonstandard(self) -> None:
        """Detect non-standard error response."""
        with pytest.raises(OAuthTokenError, match="invalid_code"):
            parse_token_response({"ok": False, "error": "invalid_code"})

    def test_error_with_description(self) -> None:
        """Include error_description in message when present."""
        with pytest.raises(OAuthTokenError, match="Code expired"):
            parse_token_response(
                {"error": "invalid_grant", "error_description": "Code expired"}
            )

    def test_invalid_response(self) -> None:
        """Raise ValidationError when required fields and error are both missing."""
        with pytest.raises(ValidationError):
            parse_token_response({"some_field": "value"})


class TestOAuthState:
    """AES-GCM encrypted OAuth state tests."""

    def test_roundtrip(self) -> None:
        """Decrypting generated state returns original values."""
        state = create_oauth_state("tk-1", "user-1", "secret")
        result = verify_oauth_state(state, "secret")
        assert result is not None
        toolkit_id, user_id, code_verifier = result
        assert toolkit_id == "tk-1"
        assert user_id == "user-1"
        assert code_verifier is None

    def test_roundtrip_with_pkce(self) -> None:
        """Decrypt state containing PKCE code_verifier."""
        state = create_oauth_state(
            "tk-2", "user-2", "secret", code_verifier="verifier123"
        )
        result = verify_oauth_state(state, "secret")
        assert result is not None
        toolkit_id, user_id, code_verifier = result
        assert toolkit_id == "tk-2"
        assert user_id == "user-2"
        assert code_verifier == "verifier123"

    def test_invalid_key(self) -> None:
        """Return None when decrypting with wrong key."""
        state = create_oauth_state("tk-3", "user-3", "secret")
        assert verify_oauth_state(state, "wrong-secret") is None

    def test_invalid_format(self) -> None:
        """Return None for invalid format."""
        assert verify_oauth_state("invalid", "secret") is None
        assert verify_oauth_state("a:b", "secret") is None

    def test_state_is_opaque(self) -> None:
        """Plaintext toolkit_id and user_id are not exposed in state."""
        state = create_oauth_state(
            "tk-secret-id", "user-secret-id", "key", code_verifier="cv-secret"
        )
        assert "tk-secret-id" not in state
        assert "user-secret-id" not in state
        assert "cv-secret" not in state

    def test_each_state_is_unique(self) -> None:
        """Same input creates different state each time."""
        s1 = create_oauth_state("tk", "u", "k")
        s2 = create_oauth_state("tk", "u", "k")
        assert s1 != s2


class TestPlatformOAuthState:
    """GitHub Platform OAuth state tests."""

    def test_roundtrip(self) -> None:
        """Verify generated platform state."""
        state = create_platform_oauth_state("secret")
        assert verify_platform_oauth_state(state, "secret") is True

    def test_invalid_key(self) -> None:
        """Return False when verifying with wrong key."""
        state = create_platform_oauth_state("secret")
        assert verify_platform_oauth_state(state, "wrong") is False

    def test_invalid_format(self) -> None:
        """Return False for invalid format."""
        assert verify_platform_oauth_state("garbage", "secret") is False

    def test_toolkit_state_is_not_platform(self) -> None:
        """toolkit OAuth state is not verified as platform state."""
        state = create_oauth_state("tk", "u", "secret")
        assert verify_platform_oauth_state(state, "secret") is False
