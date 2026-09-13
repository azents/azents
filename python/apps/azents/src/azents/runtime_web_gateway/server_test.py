"""Gateway HTTP security boundary tests."""

from datetime import UTC, datetime, timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer
from azcommon.logging import RuntimeEnvironment
from azents_runtime_control.runner_web import (
    RunnerWebIdentity,
    RunnerWebProtocol,
)

from azents.rdb.models.runtime_web import RuntimeWebAuthMode
from azents.repos.runtime_web.data import RuntimeWebEndpoint
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebAdmissionLimits,
    RuntimeWebAuthBinding,
    RuntimeWebBrokerBinding,
    RuntimeWebGatewayAuthority,
    RuntimeWebRedeemedIdentity,
)
from azents.runtime_web_gateway.policy import RuntimeWebPolicyError
from azents.runtime_web_gateway.server import (
    _browser_proof,
    _require_websocket_browser_profile,
    create_runtime_web_gateway_application,
)
from azents.runtime_web_gateway.settings import (
    RuntimeWebGatewayConfig,
    RuntimeWebGatewaySettings,
)
from azents.runtime_web_gateway.transport import RuntimeWebProxySession

_CONFIG = RuntimeWebGatewayConfig(
    enabled=True,
    auth_mode=RuntimeWebAuthMode.SHARED_COOKIE,
    configuration_version=1,
    main_web_origin="https://app.example.com",
    broker_origin="https://auth.services.example.net",
    service_suffix="services.example.net",
    cookie_domain="services.example.net",
    identity_cookie_name="__Http-Azents-Runtime-Web",
    identity_lifetime_seconds=1_800,
    chromium_min_version=152,
    chromium_max_version=152,
    request_header_bytes=32 * 1024,
    request_body_bytes=64 * 1024 * 1024,
    frame_bytes=64 * 1024,
    permissions_policy="camera=()",
)
_SETTINGS = RuntimeWebGatewaySettings.model_validate(
    {
        "runtime_env": RuntimeEnvironment.LOCAL,
        "runtime_web_gateway_enabled": True,
        "runtime_web_gateway_auth_mode": RuntimeWebAuthMode.SEPARATE_DOMAIN,
        "runtime_web_gateway_main_web_origin": "http://app.localhost",
        "runtime_web_gateway_broker_origin": "http://auth.services.localhost",
        "runtime_web_gateway_service_suffix": "services.localhost",
        "runtime_web_gateway_cookie_domain": "services.localhost",
        "runtime_web_gateway_control_endpoint": "localhost:8032",
        "runtime_web_gateway_control_allow_insecure": True,
    }
)
_NOW = datetime.now(UTC)
_ENDPOINT = RuntimeWebEndpoint(
    id="e" * 32,
    workspace_id="w" * 32,
    agent_id="a" * 32,
    agent_session_id="s" * 32,
    port=8080,
    hostname_key="endpoint",
    label="Preview",
    authority_revision=1,
    close_barrier=0,
    current_pending_request_id=None,
    current_cycle_id=None,
    created_at=_NOW,
    updated_at=_NOW,
)


class _Auth:
    async def bind_broker(
        self,
        *,
        initiation_id: str,
        now: datetime,
    ) -> RuntimeWebBrokerBinding:
        return RuntimeWebBrokerBinding(
            binding=RuntimeWebAuthBinding(
                id="b" * 32,
                initiation_id=initiation_id,
                user_id="u" * 32,
                auth_session_id="s" * 32,
                endpoint_id=_ENDPOINT.id,
                epoch=1,
                expires_at=now + timedelta(seconds=120),
                broker_bound=True,
                settled=False,
            ),
            broker_binding_secret="broker-secret",
        )

    async def redeem_ticket(
        self,
        *,
        ticket_secret: str,
        broker_binding_secret: str,
        browser_profile: str,
        now: datetime,
    ) -> RuntimeWebRedeemedIdentity:
        del ticket_secret, broker_binding_secret, browser_profile, now
        raise AssertionError("Broker authentication is not expected")


class _Authority:
    async def resolve_endpoint(
        self,
        *,
        hostname_key: str,
    ) -> RuntimeWebEndpoint | None:
        return _ENDPOINT if hostname_key == "endpoint" else None

    async def source_endpoint_matches_root(
        self,
        *,
        source_hostname_key: str,
        target_endpoint: RuntimeWebEndpoint,
    ) -> bool:
        return source_hostname_key == "source" and target_endpoint.id == _ENDPOINT.id

    async def resolve_endpoint_by_id(
        self,
        *,
        endpoint_id: str,
    ) -> RuntimeWebEndpoint | None:
        del endpoint_id
        raise AssertionError("Broker authentication is not expected")

    async def authorize(
        self,
        *,
        hostname_key: str,
        identity_secret: str,
        browser_profile: str,
        protocol: RunnerWebProtocol,
    ) -> RuntimeWebGatewayAuthority:
        del hostname_key, identity_secret, browser_profile, protocol
        raise AssertionError("Gateway admission is not expected")

    def tunnel_identity(
        self,
        *,
        authority: RuntimeWebGatewayAuthority,
        protocol: RunnerWebProtocol,
        now: datetime,
    ) -> RunnerWebIdentity:
        del authority, protocol, now
        raise AssertionError("Gateway admission is not expected")

    async def acquire_admission(
        self,
        *,
        authority: RuntimeWebGatewayAuthority,
        identity: RunnerWebIdentity,
        protocol: RunnerWebProtocol,
        limits: RuntimeWebAdmissionLimits,
        now: datetime,
    ) -> None:
        del authority, identity, protocol, limits, now
        raise AssertionError("Gateway admission is not expected")

    async def release_admission(self, *, tunnel_id: str) -> None:
        del tunnel_id
        raise AssertionError("Gateway admission is not expected")

    async def identity_and_access_current(
        self,
        *,
        authority: RuntimeWebGatewayAuthority,
    ) -> bool:
        del authority
        raise AssertionError("Gateway admission is not expected")


class _Proxy:
    def __init__(self) -> None:
        self.opened = False

    def open(self) -> RuntimeWebProxySession:
        self.opened = True
        raise AssertionError("Security rejection must not contact Runtime Control")

    async def close(self) -> None:
        pass


async def _client(proxy: _Proxy) -> TestClient:
    application = create_runtime_web_gateway_application(
        config=_CONFIG,
        settings=_SETTINGS,
        auth=_Auth(),
        authority=_Authority(),
        proxy=proxy,
    )
    client = TestClient(TestServer(application))
    await client.start_server()
    return client


def test_websocket_browser_proof_binds_prior_admission_to_endpoint() -> None:
    """A host-only proof replaces the client hint omitted by WebSocket handshakes."""
    identity_secret = "identity-secret"
    headers = {
        "User-Agent": "Mozilla/5.0 Chrome/152.0.0.0 Safari/537.36",
    }
    proof = _browser_proof(
        identity_secret=identity_secret,
        endpoint_key="endpoint",
        browser_profile="chromium-152",
    )

    assert (
        _require_websocket_browser_profile(
            headers,
            identity_secret=identity_secret,
            browser_proof=proof,
            endpoint_key="endpoint",
            config=_CONFIG,
        )
        == "chromium-152"
    )
    with pytest.raises(RuntimeWebPolicyError, match="upgrade_required"):
        _require_websocket_browser_profile(
            headers,
            identity_secret=identity_secret,
            browser_proof=proof,
            endpoint_key="other-endpoint",
            config=_CONFIG,
        )


async def test_valid_same_root_preflight_is_local_and_credentialed() -> None:
    proxy = _Proxy()
    client = await _client(proxy)
    try:
        response = await client.options(
            "/api",
            headers={
                "Host": "endpoint.services.example.net",
                "Origin": "https://source.services.example.net",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type, Authorization",
            },
        )
        assert response.status == 204
        assert (
            response.headers["Access-Control-Allow-Origin"]
            == "https://source.services.example.net"
        )
        assert response.headers["Access-Control-Allow-Credentials"] == "true"
        assert not proxy.opened
    finally:
        await client.close()


async def test_broker_auto_post_preserves_only_its_origin() -> None:
    proxy = _Proxy()
    client = await _client(proxy)
    try:
        response = await client.post(
            "/bind",
            headers={
                "Host": "auth.services.example.net",
                "Origin": "https://app.example.com",
            },
            data={"initiation_id": "i" * 32},
        )
        assert response.status == 200
        assert response.headers["Referrer-Policy"] == "strict-origin"
        content_security_policy = response.headers["Content-Security-Policy"]
        assert "form-action https://app.example.com" in content_security_policy
        assert "frame-ancestors 'none'" in content_security_policy
        assert "script-src 'nonce-runtime-web'" in content_security_policy
        assert "https://app.example.com/runtime-web/auth/bound" in await response.text()
        assert not proxy.opened
    finally:
        await client.close()


@pytest.mark.parametrize(
    "origin",
    [
        "https://source.attacker.example",
        "http://source.services.example.net",
        "https://nested.source.services.example.net",
        "https://source.services.example.net:8443",
        "https://source.services.example.net:80",
        "http://source.services.example.net:443",
    ],
)
async def test_preflight_rejects_origin_aliases_before_authority_lookup(
    origin: str,
) -> None:
    proxy = _Proxy()
    client = await _client(proxy)
    try:
        response = await client.options(
            "/api",
            headers={
                "Host": "endpoint.services.example.net",
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status == 403
        assert "Access-Control-Allow-Origin" not in response.headers
        assert not proxy.opened
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        (
            {
                "Host": "endpoint.services.example.net",
                "Service-Worker": "script",
            },
            403,
        ),
        (
            {
                "Host": "endpoint.services.example.net",
                "Sec-CH-UA": '"Chromium";v="152"',
                "User-Agent": "Chrome/152.0.0.0",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
            401,
        ),
        (
            {
                "Host": "endpoint.services.example.net",
                "Sec-CH-UA": '"Chromium";v="151"',
                "User-Agent": "Chrome/151.0.0.0",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
            426,
        ),
    ],
)
async def test_rejected_requests_never_open_trusted_transport(
    headers: dict[str, str],
    expected_status: int,
) -> None:
    proxy = _Proxy()
    client = await _client(proxy)
    try:
        response = await client.get("/api", headers=headers)
        assert response.status == expected_status
        assert response.headers["Cache-Control"] == "no-store"
        assert not proxy.opened
    finally:
        await client.close()
