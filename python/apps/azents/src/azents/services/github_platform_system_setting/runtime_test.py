"""Platform GitHub App runtime projection tests."""

from azents.core.github_credentials import (
    GitHubInstallationTarget,
    GitHubSecretsAppPlatform,
)

from .runtime import (
    PlatformGitHubAppAuthorizationReason,
    PlatformGitHubAppRuntimeService,
)


def _credentials(app_id: str) -> GitHubSecretsAppPlatform:
    return GitHubSecretsAppPlatform(
        app_id=app_id,
        installations=[
            GitHubInstallationTarget(
                installation_id="1234",
                account_login="azents-test",
                account_type="Organization",
                account_avatar_url=None,
            )
        ],
    )


def test_changed_app_identity_requires_reconnect() -> None:
    """A mismatched identity produces the App-change Public reason."""
    state = PlatformGitHubAppRuntimeService.authorization_state(
        _credentials("123"),
        effective_app_id="456",
    )

    assert state is not None
    assert state.reason is PlatformGitHubAppAuthorizationReason.APP_IDENTITY_CHANGED


def test_matching_app_identity_has_no_authorization_warning() -> None:
    """Same-App key or client-secret rotation does not affect binding."""
    state = PlatformGitHubAppRuntimeService.authorization_state(
        _credentials("123"),
        effective_app_id="123",
    )

    assert state is None
