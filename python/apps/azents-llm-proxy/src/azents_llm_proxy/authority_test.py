"""Protected authority wire, fail-closed errors and no uncertain replay."""

import asyncio
import json
import ssl
from pathlib import Path

import httpx
import pytest
from azents_llm_contract.authority import (
    ApiKeyCredential,
    AuthenticatedIdentity,
    ModelListResponse,
    TargetBinding,
)
from azents_llm_contract.settings import ModelConfiguration
from pydantic import SecretStr, ValidationError

from azents_llm_proxy.authority import (
    AuthorityClient,
    AuthorityDenied,
    AuthorityUnavailable,
    create_http_client,
)
from azents_llm_proxy.config import Settings

SERVICE = "resolver-service-sentinel-at-least-32-characters"
AGENT = "agent-bearer-sentinel"
IDENTITY = AuthenticatedIdentity(
    agent_id="agent", workspace_id="workspace", supply_id="supply", token_id="token"
)


def binding() -> TargetBinding:
    return TargetBinding(
        identity=IDENTITY,
        integration_id="integration",
        target_id="a" * 64,
        public_model="model",
        model_identifier="model",
        credential=ApiKeyCredential(
            kind="api_key", provider="openai", api_key=SecretStr("provider-sentinel")
        ),
        configuration=ModelConfiguration(
            protocol="native_responses",
            parameters=None,
            context_window_tokens=None,
            max_output_tokens=None,
            default_input_tokens=None,
            maximum_input_tokens=None,
            maximum_output_tokens=None,
            builtin_tools=(),
            supported_features=("input:text",),
            reasoning_efforts=(),
            known_default_reasoning=None,
            feature_conditions=(),
            supported_execution_options=(),
        ),
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://authority/internal/llm",
        "https://user:secret@authority/internal/llm",
        "https://authority/other",
        "https://authority/internal/llm?key=secret",
        "https://authority/internal/llm#secret",
    ],
)
def test_authority_requires_https_url_without_embedded_secrets(
    url: str,
) -> None:
    with pytest.raises(ValidationError):
        Settings(authority_url=url, resolver_key=SecretStr(SERVICE))


def test_settings_hide_secret_in_errors_and_repr() -> None:
    settings = Settings(
        authority_url="https://authority/internal/llm", resolver_key=SecretStr(SERVICE)
    )
    assert SERVICE not in repr(settings)
    assert settings.authority_url.endswith("/internal/llm/")
    with pytest.raises(ValidationError) as caught:
        Settings(
            authority_url="https://authority/internal/llm",
            resolver_key=SecretStr("short-sentinel"),
        )
    assert "short-sentinel" not in str(caught.value)


async def test_only_agent_selectors_cross_authority_and_credentials_are_private() -> (
    None
):
    captured: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            content=binding().protected_json(),
            headers={"Cache-Control": "no-store"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
        base_url="https://authority/internal/llm/",
    ) as http:
        client = AuthorityClient(http, SecretStr(SERVICE))
        result = await client.resolve(
            SecretStr(AGENT), model="model", target_id="a" * 64
        )
        assert "provider-sentinel" not in repr(result)
        assert SERVICE not in repr(client)
    assert len(captured) == 1
    assert captured[0].headers["X-Azents-LLM-Resolver"] == SERVICE
    assert json.loads(captured[0].content) == {
        "agent_token": AGENT,
        "model": "model",
        "target_id": "a" * 64,
    }
    assert SERVICE not in str(captured[0].url) and AGENT not in str(captured[0].url)


@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_errors_are_safe_and_never_retried(status: int) -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            status, text=SERVICE + AGENT, headers={"Location": "https://other.invalid"}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
        base_url="https://authority/internal/llm/",
    ) as http:
        client = AuthorityClient(http, SecretStr(SERVICE))
        with pytest.raises(
            AuthorityDenied if status in (401, 403) else AuthorityUnavailable
        ) as caught:
            await client.list_models(SecretStr(AGENT))
    assert SERVICE not in str(caught.value) and AGENT not in str(caught.value)
    assert calls == ["/internal/llm/models"]


async def test_successful_but_mismatched_binding_is_rejected() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=binding()
            .model_copy(update={"public_model": "foreign"})
            .protected_json(),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
        base_url="https://authority/internal/llm/",
    ) as http:
        with pytest.raises(AuthorityUnavailable, match="inconsistent binding"):
            await AuthorityClient(http, SecretStr(SERVICE)).resolve(
                SecretStr(AGENT), model="model", target_id="a" * 64
            )


async def test_listing_is_online_and_has_no_credential_cache() -> None:
    count = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        response = ModelListResponse(identity=IDENTITY, models=(f"model-{count}",))
        return httpx.Response(200, content=response.protected_json())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
        base_url="https://authority/internal/llm/",
    ) as http:
        client = AuthorityClient(http, SecretStr(SERVICE))
        assert (await client.list_models(SecretStr(AGENT))).models == ("model-1",)
        assert (await client.list_models(SecretStr(AGENT))).models == ("model-2",)


async def test_cancellation_is_not_rewritten_as_auth_or_replayed() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
        base_url="https://authority/internal/llm/",
    ) as http:
        with pytest.raises(asyncio.CancelledError):
            await AuthorityClient(http, SecretStr(SERVICE)).list_models(
                SecretStr(AGENT)
            )


async def test_authority_transport_keeps_tls_verification_and_zero_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def transport(**kwargs: object) -> httpx.AsyncBaseTransport:
        captured.update(kwargs)
        return httpx.MockTransport(lambda request: httpx.Response(200))

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", transport)
    roots = ssl.get_default_verify_paths().cafile
    assert roots is not None
    settings = Settings(
        authority_url="https://authority/internal/llm",
        resolver_key=SecretStr(SERVICE),
        authority_ca_file=Path(roots),
    )
    async with create_http_client(settings) as client:
        assert not client.follow_redirects
    tls = captured["verify"]
    assert isinstance(tls, ssl.SSLContext)
    assert tls.verify_mode == ssl.CERT_REQUIRED and tls.check_hostname
    assert captured["retries"] == 0 and captured["trust_env"] is False


def test_invalid_private_ca_fails_instead_of_disabling_verification(
    tmp_path: Path,
) -> None:
    settings = Settings(
        authority_url="https://authority/internal/llm",
        resolver_key=SecretStr(SERVICE),
        authority_ca_file=tmp_path / "missing-ca.crt",
    )
    with pytest.raises(FileNotFoundError):
        create_http_client(settings)
