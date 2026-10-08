"""User-account SDK behavior with deterministic intercepted provider traffic."""

import asyncio
import base64
import json
from collections.abc import Callable

import httpx
import pytest
from githubkit import BaseAuthStrategy, GitHub, UnauthAuthStrategy

from azents.core.github_auth import GitHubClientFactory
from azents.core.github_user_auth import (
    GitHubUserProviderError,
    GitHubUserTokenRejected,
    exchange_user_code,
    get_app_registration,
    get_user_identity,
    list_user_access,
    revoke_user_token,
)


def _factory(handler: Callable[[httpx.Request], httpx.Response]) -> GitHubClientFactory:
    def create(auth: BaseAuthStrategy | None) -> GitHub[BaseAuthStrategy]:
        return GitHub[BaseAuthStrategy](
            auth=auth if auth is not None else UnauthAuthStrategy(),
            async_transport=httpx.MockTransport(handler),
            auto_retry=False,
            http_cache=False,
            follow_redirects=False,
            timeout=5.0,
        )

    return create


async def _exchange(factory: GitHubClientFactory) -> str:
    result = await exchange_user_code(
        client_id="client",
        client_secret="private-client-secret",
        code="one-use-code",
        redirect_uri="https://azents.example/oauth/github/callback",
        code_verifier="private-pkce-verifier",
        client_factory=factory,
    )
    assert "private-user-token" not in repr(result)
    return result.access_token


def _installation(
    identifier: int, owner: str, *, app_id: int = 11
) -> dict[str, object]:
    return {
        "id": identifier,
        "app_id": app_id,
        "account": {
            "login": owner,
            "type": "User" if owner == "personal" else "Organization",
            "avatar_url": None,
        },
        "permissions": {"contents": "read", "issues": "write"},
    }


def _repo(identifier: int, owner: str, name: str) -> dict[str, object]:
    return {
        "id": identifier,
        "owner": {"login": owner},
        "name": name,
        "full_name": f"{owner}/{name}",
        "private": True,
        "permissions": {"pull": True, "push": False, "admin": False},
    }


@pytest.mark.asyncio
async def test_exchange_forwards_exact_callback_and_pkce_without_expiry_scope() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url == "https://github.com/login/oauth/access_token"
        assert request.method == "POST"
        assert request.headers["Accept"] == "application/json"
        assert "Authorization" not in request.headers
        assert json.loads(request.content) == {
            "client_id": "client",
            "client_secret": "private-client-secret",
            "code": "one-use-code",
            "redirect_uri": "https://azents.example/oauth/github/callback",
            "code_verifier": "private-pkce-verifier",
        }
        return httpx.Response(
            200, json={"access_token": "private-user-token", "token_type": "bearer"}
        )

    assert await _exchange(_factory(handle)) == "private-user-token"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field", ["expires_in", "refresh_token", "refresh_token_expires_in"]
)
@pytest.mark.parametrize("value", [None, 0, "private-refresh-material"])
async def test_expiring_envelope_presence_rejected_even_null_or_zero(
    field: str, value: object
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "private-user-token",
                "token_type": "bearer",
                field: value,
            },
        )

    with pytest.raises(GitHubUserTokenRejected) as caught:
        await _exchange(_factory(handle))
    assert caught.value.reason == "expiring_token"
    assert caught.value.issued_token == "private-user-token"
    assert "private-user-token" not in str(caught.value)
    assert "private-refresh-material" not in repr(caught.value)
    assert "private-user-token" not in repr(caught.value.args)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "reason", "issued"),
    [
        (
            {"error": "private-code", "error_description": "private-secret"},
            "oauth_rejected",
            None,
        ),
        (
            {"access_token": "private-user-token", "token_type": "basic"},
            "invalid_token_type",
            "private-user-token",
        ),
        (
            {"access_token": "private-user-token", "token_type": 7},
            "invalid_response",
            "private-user-token",
        ),
        ({"access_token": 7, "token_type": "bearer"}, "invalid_response", None),
        ({"access_token": " ", "token_type": "bearer"}, "invalid_response", None),
        (["private-user-token"], "invalid_response", None),
    ],
)
async def test_rejection_errors_hide_provider_payload_and_retain_cleanup_token(
    payload: object, reason: str, issued: str | None
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(GitHubUserTokenRejected) as caught:
        await _exchange(_factory(handle))
    assert caught.value.reason == reason
    assert caught.value.issued_token == issued
    for secret in ("private-code", "private-secret", "private-user-token"):
        assert secret not in str(caught.value)
        assert secret not in repr(caught.value)


@pytest.mark.asyncio
async def test_identity_and_app_registration_use_authenticated_sdk_operations() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api.github.com"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        if request.url.path == "/user":
            assert request.headers["Authorization"] == "Bearer user-token"
            return httpx.Response(
                200, json={"id": 45, "login": "account", "avatar_url": None}
            )
        assert request.url.path == "/app"
        assert request.headers["Authorization"] == "Bearer app-jwt"
        return httpx.Response(
            200, json={"id": 11, "slug": "my-app", "client_id": "client"}
        )

    factory = _factory(handle)
    user = await get_user_identity("user-token", client_factory=factory)
    app = await get_app_registration("app-jwt", client_factory=factory)
    assert user.account_id == 45 and user.login == "account"
    assert app.app_id == 11 and app.client_id == "client" and app.slug == "my-app"
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("account_id", [True, "45", None, -1])
async def test_identity_invalid_payload_is_sanitized(account_id: object) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": account_id,
                "login": "private-token-sentinel",
                "access_token": "private-token-sentinel",
            },
        )

    with pytest.raises(GitHubUserProviderError) as caught:
        await get_user_identity("user-token", client_factory=_factory(handle))
    assert caught.value.reason == "invalid_response"
    assert "private-token-sentinel" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.asyncio
async def test_access_personal_two_orgs_filter_app_and_partial_denial() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api.github.com"
        assert request.headers["Authorization"] == "Bearer user-token"
        assert request.url.params["per_page"] == "100"
        assert request.url.params["page"] == "1"
        if request.url.path == "/user/installations":
            return httpx.Response(
                200,
                json={
                    "installations": [
                        _installation(1, "personal"),
                        _installation(2, "org-one"),
                        _installation(3, "org-two"),
                        _installation(4, "other-app", app_id=99),
                    ]
                },
            )
        if request.url.path == "/user/installations/2/repositories":
            return httpx.Response(403, json={"message": "private-repo-content"})
        if request.url.path == "/user/installations/1/repositories":
            owner = "personal"
        else:
            assert request.url.path == "/user/installations/3/repositories"
            owner = "org-two"
        return httpx.Response(200, json={"repositories": [_repo(1, owner, "repo")]})

    page = await list_user_access(
        "user-token", app_id=11, cursor=None, client_factory=_factory(handle)
    )
    assert [item.account_login for item in page.installations] == [
        "personal",
        "org-one",
        "org-two",
    ]
    assert page.next_cursor is None
    personal, denied, organization = page.installations
    assert personal.repositories[0].full_name == "personal/repo"
    assert personal.repositories[0].permissions.read is True
    assert personal.repositories[0].permissions.write is False
    assert personal.app_permissions["contents"] == "read"
    assert denied.failure_reason == "target_denied"
    assert not denied.repositories_complete
    assert not denied.repositories
    assert organization.repositories_complete
    assert organization.repositories[0].full_name == "org-two/repo"
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_repository_traversal_is_bounded_and_continues_past_page_one() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/user/installations":
            return httpx.Response(
                200, json={"installations": [_installation(1, "personal")]}
            )
        assert request.url.path == "/user/installations/1/repositories"
        number = int(request.url.params["page"])
        # The adapter reads only the relation, never follows this arbitrary URL.
        headers = (
            {"Link": '<https://untrusted.example/next>; rel="next"'}
            if number < 12
            else {}
        )
        return httpx.Response(
            200,
            json={"repositories": [_repo(number, "personal", f"repo-{number}")]},
            headers=headers,
        )

    factory = _factory(handle)
    first = await list_user_access(
        "user-token", app_id=11, cursor=None, client_factory=factory
    )
    assert len(requests) == 11
    assert len(first.installations) == 10
    assert first.next_cursor is not None
    assert all(not item.repositories_complete for item in first.installations)
    second = await list_user_access(
        "user-token", app_id=11, cursor=first.next_cursor, client_factory=factory
    )
    assert len(requests) == 14
    assert [item.repositories[0].name for item in second.installations] == [
        "repo-11",
        "repo-12",
    ]
    assert second.installations[-1].repositories_complete
    assert second.next_cursor is None
    assert all(request.url.host == "api.github.com" for request in requests)


@pytest.mark.asyncio
async def test_installation_page_continues_after_filtered_first_page() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user/installations":
            if request.url.params["page"] == "1":
                return httpx.Response(
                    200,
                    json={"installations": [_installation(1, "other", app_id=99)]},
                    headers={
                        "Link": "<https://api.github.com/user/installations?page=2>; "
                        'rel="next"'
                    },
                )
            assert request.url.params["page"] == "2"
            return httpx.Response(
                200, json={"installations": [_installation(2, "org-one")]}
            )
        assert request.url.path == "/user/installations/2/repositories"
        return httpx.Response(200, json={"repositories": []})

    factory = _factory(handle)
    first = await list_user_access(
        "user-token", app_id=11, cursor=None, client_factory=factory
    )
    assert not first.installations
    assert first.next_cursor is not None
    second = await list_user_access(
        "user-token", app_id=11, cursor=first.next_cursor, client_factory=factory
    )
    assert second.installations[0].account_login == "org-one"
    assert second.next_cursor is None


@pytest.mark.asyncio
async def test_account_authentication_failure_is_not_partial_readiness() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user/installations":
            return httpx.Response(
                200, json={"installations": [_installation(1, "personal")]}
            )
        return httpx.Response(401, json={"message": "Bad credentials"})

    with pytest.raises(GitHubUserProviderError) as caught:
        await list_user_access(
            "user-token", app_id=11, cursor=None, client_factory=_factory(handle)
        )
    assert caught.value.reason == "authentication"
    assert caught.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cursor",
    [
        "not a cursor",
        "x" * 257,
        base64.urlsafe_b64encode(b'{"installation_page":0}').decode(),
        base64.urlsafe_b64encode(b'{"url":"https://untrusted.example"}').decode(),
    ],
)
async def test_invalid_cursor_never_causes_provider_io(cursor: str) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid cursor must be rejected before provider I/O")

    with pytest.raises(ValueError, match="Invalid GitHub access continuation cursor"):
        await list_user_access(
            "user-token", app_id=11, cursor=cursor, client_factory=_factory(handle)
        )


@pytest.mark.asyncio
async def test_strict_revocation_targets_captured_token_only() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "DELETE"
        assert request.url.path == "/applications/client/token"
        assert request.url.host == "api.github.com"
        assert request.headers["Authorization"] == (
            "Basic " + base64.b64encode(b"client:private-secret").decode()
        )
        assert json.loads(request.content) == {"access_token": "retired-token"}
        return httpx.Response(204)

    await revoke_user_token(
        client_id="client",
        client_secret="private-secret",
        token="retired-token",
        client_factory=_factory(handle),
    )
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 404, 422, 500, 503])
async def test_revocation_failure_surfaces_sanitized_without_retry_or_false_success(
    status_code: int,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, json={"message": "private-secret"})

    with pytest.raises(GitHubUserProviderError) as caught:
        await revoke_user_token(
            client_id="client",
            client_secret="private-secret",
            token="retired-token",
            client_factory=_factory(handle),
        )
    assert caught.value.status_code == status_code
    assert "private-secret" not in str(caught.value)
    assert "retired-token" not in repr(caught.value)
    assert caught.value.__suppress_context__
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_exchange_transport_failure_is_single_request_and_sanitized() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("private-provider-detail", request=request)

    with pytest.raises(GitHubUserProviderError) as caught:
        await _exchange(_factory(handle))
    assert caught.value.reason == "provider_unavailable"
    assert caught.value.status_code is None
    assert "private-provider-detail" not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [RuntimeError("programming defect"), asyncio.CancelledError()]
)
async def test_revocation_preserves_programming_failure_and_cancellation(
    failure: BaseException,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise failure

    with pytest.raises(type(failure)):
        await revoke_user_token(
            client_id="client",
            client_secret="secret",
            token="token",
            client_factory=_factory(handle),
        )
