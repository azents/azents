"""Gateway HTTP security boundary tests."""

from datetime import UTC, datetime, timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer
from azcommon.logging import RuntimeEnvironment
from azents_runtime_control.runner_web import (
    RunnerWebIdentity,
    RunnerWebProtocol,
)
from multidict import CIMultiDict

from azents.rdb.models.runtime_web import RuntimeWebAuthMode
from azents.repos.runtime_web.data import RuntimeWebEndpoint
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebAdmissionLimits,
    RuntimeWebAuthBinding,
    RuntimeWebBrokerBinding,
    RuntimeWebGatewayAuthority,
    RuntimeWebRedeemedIdentity,
)
from azents.runtime_web_gateway.server import create_runtime_web_gateway_application
from azents.runtime_web_gateway.settings import (
    RuntimeWebGatewayConfig,
    RuntimeWebGatewaySettings,
)
from azents.runtime_web_gateway.transport import RuntimeWebProxySession
from azents.services.runtime_web.gateway_authority import (
    RuntimeWebGatewayAuthorityCode,
    RuntimeWebGatewayAuthorityError,
)

_CONFIG = RuntimeWebGatewayConfig(
    enabled=True,
    auth_mode=RuntimeWebAuthMode.SHARED_COOKIE,
    main_web_origin="https://app.example.com",
    broker_origin="https://auth.services.example.net",
    service_suffix="services.example.net",
    cookie_domain="services.example.net",
    identity_cookie_name="__Http-Azents-Runtime-Web",
    identity_lifetime_seconds=1_800,
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
        now: datetime,
    ) -> RuntimeWebRedeemedIdentity:
        del ticket_secret, broker_binding_secret, now
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
        protocol: RunnerWebProtocol,
    ) -> RuntimeWebGatewayAuthority:
        del hostname_key, identity_secret, protocol
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


class _BrowserNeutralAuthority(_Authority):
    def __init__(self) -> None:
        self.authorize_calls: list[tuple[str, str, RunnerWebProtocol]] = []

    async def authorize(
        self,
        *,
        hostname_key: str,
        identity_secret: str,
        protocol: RunnerWebProtocol,
    ) -> RuntimeWebGatewayAuthority:
        self.authorize_calls.append((hostname_key, identity_secret, protocol))
        raise RuntimeWebGatewayAuthorityError(RuntimeWebGatewayAuthorityCode.GONE)


async def _client(
    proxy: _Proxy,
    *,
    authority: _Authority | None = None,
) -> TestClient:
    application = create_runtime_web_gateway_application(
        config=_CONFIG,
        settings=_SETTINGS,
        auth=_Auth(),
        authority=authority or _Authority(),
        proxy=proxy,
    )
    client = TestClient(TestServer(application))
    await client.start_server()
    return client


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
                "User-Agent": "Mozilla/5.0 Firefox/143.0",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
            401,
        ),
        (
            {
                "Host": "endpoint.services.example.net",
                "User-Agent": "Mozilla/5.0 Version/26.0 Safari/605.1.15",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
            401,
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


@pytest.mark.parametrize(
    ("user_agent", "upgrade", "expected_protocol"),
    [
        ("Mozilla/5.0 Firefox/143.0", None, RunnerWebProtocol.HTTP),
        (
            "Mozilla/5.0 Version/26.0 Safari/605.1.15",
            "websocket",
            RunnerWebProtocol.WEBSOCKET,
        ),
    ],
)
async def test_identity_reaches_authority_without_vendor_signals(
    user_agent: str,
    upgrade: str | None,
    expected_protocol: RunnerWebProtocol,
) -> None:
    proxy = _Proxy()
    authority = _BrowserNeutralAuthority()
    client = await _client(proxy, authority=authority)
    headers = {
        "Host": "endpoint.services.example.net",
        "Cookie": "__Http-Azents-Runtime-Web=opaque-secret",
        "User-Agent": user_agent,
    }
    if upgrade is not None:
        headers["Upgrade"] = upgrade
    try:
        response = await client.get("/api", headers=headers)
        assert response.status == 410
        assert authority.authorize_calls == [
            ("endpoint", "opaque-secret", expected_protocol)
        ]
        assert not proxy.opened
    finally:
        await client.close()


@pytest.mark.parametrize(
    "cookies",
    [
        [
            (
                "Cookie",
                "__Http-Azents-Runtime-Web=first; __Http-Azents-Runtime-Web=second",
            )
        ],
        [
            (
                "Cookie",
                "__Http-Azents-Runtime-Web=same; __Http-Azents-Runtime-Web=same",
            )
        ],
        [
            ("Cookie", "__Http-Azents-Runtime-Web=first"),
            ("Cookie", "__Http-Azents-Runtime-Web=second"),
        ],
        [
            ("Cookie", "__Http-Azents-Runtime-Web=same"),
            ("Cookie", "__Http-Azents-Runtime-Web=same"),
        ],
    ],
)
async def test_duplicate_identity_cookie_is_rejected_before_authority_lookup(
    cookies: list[tuple[str, str]],
) -> None:
    proxy = _Proxy()
    client = await _client(proxy)
    headers = CIMultiDict(cookies)
    headers["Host"] = "endpoint.services.example.net"
    try:
        response = await client.get("/api", headers=headers)
        assert response.status == 400
        assert not proxy.opened
    finally:
        await client.close()


@pytest.mark.parametrize(
    "cookies",
    [
        [
            (
                "Cookie",
                "__Host-Azents-Runtime-Web-Broker-Binding=first; "
                "__Host-Azents-Runtime-Web-Broker-Binding=second",
            )
        ],
        [
            (
                "Cookie",
                "__Host-Azents-Runtime-Web-Broker-Binding=same; "
                "__Host-Azents-Runtime-Web-Broker-Binding=same",
            )
        ],
        [
            ("Cookie", "__Host-Azents-Runtime-Web-Broker-Binding=first"),
            ("Cookie", "__Host-Azents-Runtime-Web-Broker-Binding=second"),
        ],
        [
            ("Cookie", "__Host-Azents-Runtime-Web-Broker-Binding=same"),
            ("Cookie", "__Host-Azents-Runtime-Web-Broker-Binding=same"),
        ],
    ],
)
async def test_duplicate_broker_binding_cookie_is_rejected_before_ticket_redeem(
    cookies: list[tuple[str, str]],
) -> None:
    proxy = _Proxy()
    client = await _client(proxy)
    headers = CIMultiDict(cookies)
    headers["Host"] = "auth.services.example.net"
    headers["Origin"] = "https://app.example.com"
    try:
        response = await client.post(
            "/redeem",
            headers=headers,
            data={"ticket": "ticket-secret"},
        )
        assert response.status == 400
        assert not proxy.opened
    finally:
        await client.close()
