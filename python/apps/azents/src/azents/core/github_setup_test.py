"""Setup SDK projections reject malformed identity and protect provider secrets."""

import httpx
import pytest
from pydantic import ValidationError

from azents.core.github_setup import (
    GitHubAppSetupVerification,
    GitHubSetupTransport,
)
from azents.core.github_user_auth import (
    GitHubUserProviderError,
    get_setup_app,
    get_setup_installation,
    get_setup_installation_token,
)
from azents.core.github_user_auth_test import _factory, _installation
from azents.core.github_user_creation import GitHubUserCreationFinalSettings
from azents.repos.toolkit.data import ToolkitCreate


async def test_metadata_uses_authenticated_sdk_and_reads_current_name_every_call() -> (
    None
):
    names = iter(["Original App", "Renamed App"])

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.github.com/app"
        assert request.headers["Authorization"] == "Bearer secret-jwt"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        return httpx.Response(
            200,
            json={
                "id": 123,
                "name": next(names),
                "slug": "actual-app",
                "private_key": "secret-provider-extension",
            },
        )

    factory = _factory(handle)
    first = await get_setup_app("secret-jwt", app_id="123", client_factory=factory)
    second = await get_setup_app("secret-jwt", app_id="123", client_factory=factory)
    assert first.name == "Original App" and second.name == "Renamed App"
    assert first.model_dump() == {
        "app_id": "123",
        "name": "Original App",
        "slug": "actual-app",
    }
    assert "secret" not in first.model_dump_json()


@pytest.mark.parametrize(
    "payload",
    [
        {"id": 124, "name": "Wrong App", "slug": "wrong"},
        {"id": True, "name": "Wrong App", "slug": "wrong"},
        {"id": "123", "name": "Wrong App", "slug": "wrong"},
        {"id": 123, "name": "", "slug": "wrong"},
        {"id": 123, "slug": "wrong"},
        {"id": 123, "name": {"token": "secret-sentinel"}, "slug": "wrong"},
    ],
)
async def test_metadata_rejects_mismatch_and_malformed_provider_values(
    payload: object,
) -> None:
    with pytest.raises(GitHubUserProviderError) as caught:
        await get_setup_app(
            "secret-jwt",
            app_id="123",
            client_factory=_factory(lambda _: httpx.Response(200, json=payload)),
        )
    assert caught.value.reason == "invalid_response"
    assert "secret-sentinel" not in str(caught.value)


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
async def test_metadata_errors_never_return_fabricated_names(status: int) -> None:
    with pytest.raises(GitHubUserProviderError) as caught:
        await get_setup_app(
            "secret-jwt",
            app_id="123",
            client_factory=_factory(
                lambda _: httpx.Response(
                    status, json={"message": "secret-provider-sentinel"}
                )
            ),
        )
    assert caught.value.status_code == status
    assert "secret-provider-sentinel" not in str(caught.value)


async def test_selected_installations_each_use_public_sdk_get_and_strict_identity() -> (
    None
):
    observed: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        observed.append(request.url.path)
        installation_id = int(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(
            200,
            json=_installation(installation_id, f"owner-{installation_id}", app_id=123),
        )

    for identifier in ["501", "502"]:
        installation = await get_setup_installation(
            "secret-jwt",
            app_id="123",
            installation_id=identifier,
            client_factory=_factory(handle),
        )
        assert installation.account_login == f"owner-{identifier}"
    assert observed == ["/app/installations/501", "/app/installations/502"]


@pytest.mark.parametrize("identifier,app_id", [(True, 123), (502, 123), (501, 124)])
async def test_installation_rejects_legacy_boolean_and_mismatched_ids(
    identifier: object, app_id: int
) -> None:
    payload = _installation(501, "owner", app_id=app_id)
    payload["id"] = identifier
    with pytest.raises(GitHubUserProviderError) as caught:
        await get_setup_installation(
            "secret-jwt",
            app_id="123",
            installation_id="501",
            client_factory=_factory(lambda _: httpx.Response(200, json=payload)),
        )
    assert caught.value.reason == "invalid_response"


async def test_probe_token_uses_sdk_and_has_private_representation() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/app/installations/501/access_tokens"
        assert request.method == "POST"
        return httpx.Response(201, json={"token": "secret-probe-token"})

    token = await get_setup_installation_token(
        "secret-jwt", installation_id="501", client_factory=_factory(handle)
    )
    assert token.access_token == "secret-probe-token"
    assert "secret-probe-token" not in repr(token)


@pytest.mark.parametrize("identifier", ["0", "01", "-1", "abc", "١", 1, True])
def test_new_request_numeric_ids_do_not_inherit_legacy_scalar_compatibility(
    identifier: object,
) -> None:
    with pytest.raises(ValidationError):
        GitHubAppSetupVerification.model_validate(
            {
                "github_auth_type": "github_app",
                "app_id": identifier,
                "private_key": "secret-key",
                "installation_ids": ["501"],
                "transport": {"toolsets": [], "timeout": 30.0},
            }
        )


def test_secret_inputs_are_excluded_from_model_representations() -> None:
    request = GitHubAppSetupVerification(
        github_auth_type="github_app",
        app_id="123",
        private_key="secret-key",
        installation_ids=["501"],
        transport=GitHubSetupTransport(toolsets=[], timeout=30.0),
    )
    assert "secret-key" not in repr(request)


def test_final_overlay_preserves_locked_authentication_and_owner_authority() -> None:
    settings = GitHubUserCreationFinalSettings(
        name="  Final Name  ",
        slug="  Final-Slug  ",
        description="description",
        prompt="prompt",
        enabled=False,
        always_expose_tools=True,
        toolsets=["projects", "future_group"],
        timeout=8.0,
        inject_runtime_environment=True,
        runtime_risk_acknowledged=True,
    )
    desired = ToolkitCreate(
        workspace_id="workspace",
        owner_agent_id="exact-agent",
        toolkit_type="github",
        name="Old",
        slug="old",
        config={"github_auth_type": "github_app_user"},
        credentials="secret-credentials",
        always_expose_tools=False,
    )
    final = settings.prepare(canonical_name="GitHub").apply(desired)
    assert final.name == "Final Name" and final.slug == "final_slug"
    assert (
        final.workspace_id == desired.workspace_id
        and final.owner_agent_id == desired.owner_agent_id
    )
    assert final.credentials == desired.credentials
    assert final.config == {
        "github_auth_type": "github_app_user",
        "toolsets": ["projects", "future_group"],
        "timeout": 8.0,
        "inject_runtime_environment": True,
    }
    assert "runtime_risk_acknowledged" not in final.config


@pytest.mark.parametrize("name,slug", [(None, None), (" ", " ")])
def test_final_null_or_blank_identifiers_use_canonical_create_defaults(
    name: str | None, slug: str | None
) -> None:
    settings = GitHubUserCreationFinalSettings(
        name=name,
        slug=slug,
        description=None,
        prompt=None,
        enabled=True,
        always_expose_tools=False,
        toolsets=[],
        timeout=30.0,
        inject_runtime_environment=False,
        runtime_risk_acknowledged=False,
    )
    overlay = settings.prepare(canonical_name="GitHub")
    assert overlay.name == "GitHub" and overlay.slug == "github"


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_setup_transport_requires_a_finite_positive_timeout(timeout: float) -> None:
    with pytest.raises(ValidationError):
        GitHubSetupTransport(toolsets=[], timeout=timeout)
