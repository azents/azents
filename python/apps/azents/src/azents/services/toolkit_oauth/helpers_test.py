"""Pure Toolkit OAuth decoding, credential merge and provider error contracts."""

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from azents.core.github_installation import decode_github_installations
from azents.core.mcp_discovery import DiscoveryError, OAuthServerMetadata
from azents.core.oauth2 import OAuthTokenError, OAuthTokenResponse
from azents.core.tools import McpToolkitConfig
from azents.engine.tools.notion import NotionToolkitProvider
from azents.repos.toolkit_oauth_data import GithubInstallationRecord
from azents.services.toolkit_oauth import helpers
from azents.services.toolkit_oauth.data import (
    ToolkitConnectionTestInput,
    ToolkitOAuthError,
    ToolkitOAuthFailureReason,
)


def test_installation_decode_preserves_order_duplicates_and_avatar_distinction() -> (
    None
):
    """Persistence accepts empty/default avatars; Public projection stays strict."""
    rows: list[dict[str, object]] = [
        {"id": 1, "account": {"login": "first", "type": "User"}},
        {"id": "2", "account": {"login": "invalid", "type": "User"}},
        {"id": 3, "account": []},
        {"id": 4, "account": {"login": None, "type": "User"}},
        {"id": 1, "account": {"login": "last", "type": "User", "avatar_url": 9}},
        {"id": True, "account": {"login": "bool", "type": "User", "avatar_url": ""}},
        {
            "id": 5,
            "account": {
                "login": "org",
                "type": "Organization",
                "avatar_url": "https://example.test/avatar",
            },
        },
    ]
    snapshots = decode_github_installations(rows)
    decoded = helpers.decode_installations(snapshots)
    assert decoded == (
        GithubInstallationRecord(1, "first", "User", ""),
        GithubInstallationRecord(1, "last", "User", ""),
        GithubInstallationRecord(True, "bool", "User", ""),
        GithubInstallationRecord(
            5, "org", "Organization", "https://example.test/avatar"
        ),
    )
    projected = helpers.project_installations(snapshots)
    assert [(item.id, item.account_login) for item in projected] == [
        (True, "bool"),
        (5, "org"),
    ]
    assert (
        helpers.decode_installations(decode_github_installations([{"id": None}])) == ()
    )
    assert (
        helpers.project_installations(
            decode_github_installations([{"id": 1, "account": None}])
        )
        == ()
    )


@pytest.mark.parametrize(
    ("saved", "submitted", "expected"),
    [
        (
            '{"type":"pat","token":"saved","nested":{"key":"saved"}}',
            {"type": "pat", "token": "", "nested": {"key": None, "extra": "new"}},
            {
                "type": "pat",
                "token": "saved",
                "nested": {"key": "saved", "extra": "new"},
            },
        ),
        (
            '{"type":"pat","token":"saved"}',
            {"type": "github_app_platform", "installations": []},
            {"type": "github_app_platform", "installations": []},
        ),
        ("not-json", {"type": "pat", "token": "new"}, {"type": "pat", "token": "new"}),
        ("[]", None, None),
        (None, {}, None),
    ],
)
def test_saved_redacted_merge_preserves_blank_null_and_discriminator(
    saved: str | None,
    submitted: dict[str, object] | None,
    expected: dict[str, object] | None,
) -> None:
    """Existing saved values survive blanks; changed credential type replaces."""
    result = helpers.merge_saved_test_credentials(
        ToolkitConnectionTestInput("github", {}, submitted, "toolkit-1"), saved
    )
    assert (json.loads(result) if result is not None else None) == expected


def test_kubernetes_merge_prunes_clusters_and_replaces_changed_auth_type() -> None:
    """Only configured clusters retain credentials of their current auth type."""
    saved = json.dumps(
        {
            "clusters": {
                "keep": {"type": "token", "token": "saved"},
                "changed": {"type": "token", "token": "old"},
                "removed": {"type": "token", "token": "unused"},
            }
        }
    )
    request = ToolkitConnectionTestInput(
        "kubernetes",
        {
            "clusters": [
                {"name": "keep", "auth_type": "token"},
                {"name": "changed", "auth_type": "kubeconfig"},
            ]
        },
        {
            "clusters": {
                "keep": {"type": "token", "token": ""},
                "changed": {"type": "kubeconfig", "kubeconfig": "new"},
            }
        },
        "toolkit-1",
    )
    result = helpers.merge_saved_test_credentials(request, saved)
    assert result is not None
    assert json.loads(result) == {
        "clusters": {
            "keep": {"type": "token", "token": "saved"},
            "changed": {"type": "kubeconfig", "kubeconfig": "new"},
        }
    }


@pytest.mark.parametrize("raw", [None, "[]", "not-json", '{"type":"none"}'])
def test_invalid_manual_client_credentials_keep_existing_no_client_fallback(
    raw: str | None,
) -> None:
    """Invalid stored secrets remain absence instead of a new fatal error."""
    assert helpers.extract_oauth_client_credentials(raw) is None


def test_registered_provider_mcp_resolution_and_manual_credentials() -> None:
    """Registered providers keep their canonical MCP endpoint/auth projection."""
    resolved = helpers.resolve_mcp_config(
        "notion", {}, {"notion": NotionToolkitProvider()}
    )
    assert resolved.auth_type == "oauth2"
    client = helpers.extract_oauth_client_credentials(
        '{"type":"oauth2","client_id":"client","client_secret":"secret"}'
    )
    assert client is not None
    assert client.client_id == "client"
    assert client.client_secret == "secret"
    assert (
        helpers.extract_oauth_client_credentials(
            '{"type":"oauth2","client_id":"client","client_secret":null}'
        )
        is None
    )


@pytest.mark.parametrize("explicit", [False, True])
async def test_discovery_error_preserves_explicit_endpoint_fallback(
    monkeypatch: pytest.MonkeyPatch, explicit: bool
) -> None:
    """Discovery fails as before unless both explicit endpoints were configured."""

    async def discover(*args: object, **kwargs: object) -> OAuthServerMetadata:
        raise DiscoveryError("unavailable")

    monkeypatch.setattr(helpers, "discover_oauth_metadata", discover)
    config = McpToolkitConfig(
        server_url="https://mcp.test",
        auth_type="oauth2",
        auth_url="https://mcp.test/auth" if explicit else None,
        token_url="https://mcp.test/token" if explicit else None,
    )
    if explicit:
        metadata = await helpers.discover_required_metadata(config, None)
        assert metadata.authorization_endpoint == "https://mcp.test/auth"
        assert metadata.token_endpoint == "https://mcp.test/token"
        assert metadata.registration_endpoint is None
    else:
        with pytest.raises(ToolkitOAuthError) as raised:
            await helpers.discover_required_metadata(config, None)
        assert raised.value.reason is ToolkitOAuthFailureReason.INVALID_REQUEST
        assert raised.value.detail == "OAuth metadata discovery failed: unavailable"


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (
            httpx.HTTPStatusError(
                "denied",
                request=httpx.Request("POST", "https://mcp.test/token"),
                response=httpx.Response(401),
            ),
            ToolkitOAuthFailureReason.TOKEN_REJECTED,
        ),
        (OAuthTokenError("invalid_grant"), ToolkitOAuthFailureReason.TOKEN_REJECTED),
        (
            ValidationError.from_exception_data(
                "OAuthTokenResponse",
                [{"type": "missing", "loc": ("access_token",), "input": {}}],
            ),
            ToolkitOAuthFailureReason.TOKEN_REJECTED,
        ),
        (
            httpx.HTTPStatusError(
                "unavailable",
                request=httpx.Request("POST", "https://mcp.test/token"),
                response=httpx.Response(503),
            ),
            None,
        ),
        (RuntimeError("unexpected"), None),
        (asyncio.CancelledError(), None),
    ],
)
async def test_token_errors_classify_only_existing_expected_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    reason: ToolkitOAuthFailureReason | None,
) -> None:
    """Provider 4xx/OAuth/shape errors map; 5xx/unexpected/cancel remain transparent."""

    async def exchange(**kwargs: object) -> OAuthTokenResponse:
        raise failure

    monkeypatch.setattr(helpers, "exchange_authorization_code", exchange)
    with pytest.raises(
        ToolkitOAuthError if reason is not None else type(failure)
    ) as raised:
        await helpers.exchange_and_handle_errors(
            token_url="https://mcp.test/token",
            client_id="client",
            client_secret=None,
            code="code",
            redirect_uri="https://app.test/callback",
            code_verifier="verifier",
            resource="https://mcp.test",
            proxy_url=None,
            toolkit_id="toolkit-1",
            user_id="user-1",
        )
    if reason is not None:
        assert isinstance(raised.value, ToolkitOAuthError)
        assert raised.value.reason is reason
    else:
        assert raised.value is failure
