"""Provider identity OAuth attempt model contract tests."""

from azents.rdb.models.external_account_oauth import (
    RDBExternalAccountOAuthAttempt,
    external_account_oauth_attempt_status_enum,
)


def test_attempt_schema_contains_hash_only_and_session_binding() -> None:
    """Attempt persistence keeps state hash and auth-session fences."""
    columns = set(RDBExternalAccountOAuthAttempt.__table__.columns.keys())

    assert {
        "state_hash",
        "user_id",
        "auth_session_id",
        "setting_generation",
        "redirect_uri",
        "encrypted_pkce_verifier",
        "status",
        "expires_at",
        "claimed_at",
        "completed_at",
        "failed_at",
        "failure_code",
    }.issubset(columns)
    assert "authorization_code" not in columns
    assert "access_token" not in columns
    assert "refresh_token" not in columns
    assert external_account_oauth_attempt_status_enum.name == (
        "external_account_oauth_attempt_status"
    )
