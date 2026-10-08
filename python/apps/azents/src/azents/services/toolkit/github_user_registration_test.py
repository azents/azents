"""Write-only registration edits preserve only same-App secret authority."""

import json

import pytest
from pydantic import ValidationError

from azents.core.github_credentials import GitHubSecretsAppUser
from azents.services.toolkit.github_user_registration import (
    merge_github_user_registration,
)


def _saved() -> str:
    return json.dumps(
        {
            "type": "github_app_user",
            "app_id": "123",
            "client_id": "Iv1.original",
            "private_key": "saved-app-key",
            "client_secret": "saved-client-secret",
        }
    )


def test_omitted_same_app_write_only_fields_are_retained() -> None:
    merged = merge_github_user_registration(
        _saved(),
        {
            "type": "github_app_user",
            "app_id": "123",
            "client_id": "Iv1.original",
        },
    )
    registration = GitHubSecretsAppUser.model_validate(merged)
    assert registration.private_key == "saved-app-key"
    assert registration.client_secret == "saved-client-secret"


def test_same_app_secret_rotation_replaces_only_submitted_secret() -> None:
    merged = merge_github_user_registration(
        _saved(),
        {
            "type": "github_app_user",
            "app_id": "123",
            "client_id": "Iv1.original",
            "client_secret": "new-client-secret",
        },
    )
    assert merged["client_secret"] == "new-client-secret"
    assert merged["private_key"] == "saved-app-key"


def test_new_app_cannot_inherit_saved_registration_secrets() -> None:
    merged = merge_github_user_registration(
        _saved(),
        {
            "type": "github_app_user",
            "app_id": "999",
            "client_id": "Iv1.new-app",
        },
    )
    assert "private_key" not in merged
    assert "client_secret" not in merged
    with pytest.raises(ValidationError):
        GitHubSecretsAppUser.model_validate(merged)


def test_different_oauth_client_cannot_inherit_client_secret() -> None:
    merged = merge_github_user_registration(
        _saved(),
        {
            "type": "github_app_user",
            "app_id": "123",
            "client_id": "Iv1.changed",
        },
    )
    assert "client_secret" not in merged
    assert merged["private_key"] == "saved-app-key"


def test_explicit_null_secret_is_not_treated_as_omission() -> None:
    merged = merge_github_user_registration(
        _saved(),
        {
            "type": "github_app_user",
            "app_id": "123",
            "client_id": "Iv1.original",
            "client_secret": None,
        },
    )
    assert merged["client_secret"] is None
    with pytest.raises(ValidationError):
        GitHubSecretsAppUser.model_validate(merged)


def test_secret_only_edit_retains_saved_identity() -> None:
    merged = merge_github_user_registration(
        _saved(), {"type": "github_app_user", "client_secret": "rotated-secret"}
    )
    registration = GitHubSecretsAppUser.model_validate(merged)
    assert registration.app_id == "123"
    assert registration.client_id == "Iv1.original"
    assert registration.client_secret == "rotated-secret"
    assert registration.private_key == "saved-app-key"


def test_missing_identity_is_not_filled_for_a_new_registration() -> None:
    merged = merge_github_user_registration(
        None, {"type": "github_app_user", "client_secret": "new-secret"}
    )
    assert "app_id" not in merged
    assert "client_id" not in merged
    with pytest.raises(ValidationError):
        GitHubSecretsAppUser.model_validate(merged)
