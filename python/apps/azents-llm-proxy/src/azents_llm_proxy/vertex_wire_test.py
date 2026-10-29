"""Real service-account JWTs with warm-cache isolation and online denial."""

import json
from collections import Counter
from dataclasses import dataclass
from urllib.parse import parse_qs

import google.auth
import httpx
import jwt
import pytest
import requests
import respx
from azents_llm_contract.authority import VertexCredential
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from azents_llm_proxy import bootstrap
from azents_llm_proxy.authority import AuthorityClient
from azents_llm_proxy.authority_test import SERVICE, binding
from azents_llm_proxy.proxy_test import setup_proxy
from azents_llm_proxy.tool_wire_test import google_result

pytestmark = pytest.mark.usefixtures("protected_provider_clients")


@dataclass(frozen=True)
class Account:
    document: str
    public_key: rsa.RSAPublicKey
    email: str


def account(suffix: str) -> Account:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    email = f"{suffix}@fixture-project.iam.gserviceaccount.com"
    return Account(
        document=json.dumps(
            {
                "type": "service_account",
                "project_id": "fixture-project",
                "private_key_id": "fixture-" + suffix,
                "private_key": key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                ).decode(),
                "client_email": email,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        ),
        public_key=key.public_key(),
        email=email,
    )


async def test_warm_vertex_token_cache_never_replaces_online_agent_authority(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = "gemini-3.1-pro-preview"
    accounts = {suffix: account(suffix) for suffix in ("a", "b")}
    exchanges: list[str] = []
    inference: list[str] = []
    allow_a = True

    def deny_ambient(*args: object, **kwargs: object) -> None:
        raise AssertionError("Ambient Google identity reached.")

    monkeypatch.setattr(google.auth, "default", deny_ambient)
    monkeypatch.setattr(google.auth, "load_credentials_from_file", deny_ambient)

    def token_request(
        session: requests.Session, method: str, url: str, **kwargs: object
    ) -> requests.Response:
        assert method == "POST" and url == "https://oauth2.googleapis.com/token"
        data = kwargs["data"]
        assert isinstance(data, (str, bytes))
        body = parse_qs(data.decode() if isinstance(data, bytes) else data)
        assert body["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
        assertion = body["assertion"][0]
        claims = jwt.decode(assertion, options={"verify_signature": False})
        suffix = claims["iss"].split("@")[0]
        verified = jwt.decode(
            assertion, accounts[suffix].public_key, algorithms=["RS256"], audience=url
        )
        assert verified["iss"] == accounts[suffix].email
        exchanges.append(suffix)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(
            {
                "access_token": "fixture-vertex-" + suffix,
                "expires_in": 3600,
                "token_type": "Bearer",
            }
        ).encode()
        response.headers["Content-Type"] = "application/json"
        return response

    monkeypatch.setattr(requests.Session, "request", token_request)

    def authority(request: httpx.Request) -> httpx.Response:
        suffix = json.loads(request.content)["agent_token"][-1]
        if suffix == "a" and not allow_a:
            return httpx.Response(401, json={"detail": "Denied."})
        original = binding()
        value = original.model_copy(
            update={
                "public_model": model,
                "model_identifier": model,
                "identity": original.identity.model_copy(
                    update={"agent_id": "agent-" + suffix}
                ),
                "credential": VertexCredential(
                    kind="google_vertex_ai",
                    service_account_json=SecretStr(accounts[suffix].document),
                    project_id="fixture-project",
                    location="us-central1",
                ),
                "configuration": original.configuration.model_copy(
                    update={"protocol": "google"}
                ),
            }
        )
        return httpx.Response(200, content=value.protected_json())

    def provider(request: httpx.Request) -> httpx.Response:
        inference.append(request.headers["authorization"])
        assert request.url.host == "us-central1-aiplatform.googleapis.com"
        return httpx.Response(200, json=google_result(image=False))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            route = router.route(
                method="POST", host="us-central1-aiplatform.googleapis.com"
            ).mock(side_effect=provider)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                body = {
                    "model": model,
                    "input": "vertex-private-prompt",
                    "metadata": {"azents_target_id": "a" * 64},
                }
                for suffix in ("a", "b", "a"):
                    result = await client.post(
                        "/v1/responses",
                        headers={"Authorization": "Bearer agent-" + suffix},
                        json=body,
                    )
                    assert result.status_code == 200, result.text
                allow_a = False
                denied = await client.post(
                    "/v1/responses",
                    headers={"Authorization": "Bearer agent-a"},
                    json=body,
                )
                assert denied.status_code == 401
                result = await client.post(
                    "/v1/responses",
                    headers={"Authorization": "Bearer agent-b"},
                    json=body,
                )
                assert result.status_code == 200
            assert route.call_count == 4
    assert inference == [
        "Bearer fixture-vertex-" + suffix for suffix in ("a", "b", "a", "b")
    ]
    assert Counter(exchanges) == {"a": 1, "b": 1}
    captured = capsys.readouterr()
    for sentinel in [
        "fixture-vertex-a",
        "fixture-vertex-b",
        "vertex-private-prompt",
        "BEGIN PRIVATE KEY",
    ]:
        assert sentinel not in captured.out + captured.err + caplog.text
    assert bootstrap.context.current.get() is None
