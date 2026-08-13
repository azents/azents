"""Mitmproxy addon conformance and redaction tests."""

import asyncio
import json
import logging
from unittest.mock import MagicMock

import pytest
from mitmproxy import connection, http, tcp, tls, udp
from mitmproxy.options import Options
from mitmproxy.proxy.context import Context
from mitmproxy.proxy.server_hooks import ServerConnectionHookData

from azents_runtime_proxy.addon import AzentsProxyAddon
from azents_runtime_proxy.policy import ProxyPolicy, parse_proxy_policy


def _policy() -> ProxyPolicy:
    return parse_proxy_policy(
        {
            "schema_version": 1,
            "runtime_id": "runtime-1",
            "configuration_sequence": 4,
            "configuration_digest": "a" * 64,
            "domain_policy": {
                "mode": "allowlist",
                "allowed_domains": ["api.example.com"],
                "denied_domains": [],
            },
            "network_policy": {
                "allowed_cidrs": ["203.0.113.0/24"],
                "denied_cidrs": [],
            },
            "ca_fingerprint": "b" * 64,
            "artifact_digest": "c" * 64,
        },
        digest="d" * 64,
    )


async def _resolver(host: str, port: int) -> tuple[str, ...]:
    del port
    if host == "api.example.com":
        return ("203.0.113.10", "203.0.113.11")
    return ("198.51.100.10",)


def _flow(url: str, *, host_header: str | None = None) -> http.HTTPFlow:
    client = connection.Client(
        peername=("127.0.0.1", 40_000),
        sockname=("127.0.0.1", 8080),
    )
    server = connection.Server(address=None)
    flow = http.HTTPFlow(client, server, live=True)
    flow.request = http.Request.make("GET", url)
    if host_header is not None:
        flow.request.headers["host"] = host_header
    return flow


@pytest.mark.asyncio
async def test_request_authorization_pins_selected_ip_and_preserves_sni(
    caplog: pytest.LogCaptureFixture,
) -> None:
    addon = AzentsProxyAddon(_policy(), readiness_port=0, resolver=_resolver)
    flow = _flow("https://api.example.com/path?token=secret")
    flow.request.headers["authorization"] = "Bearer secret"
    flow.request.content = b"private request body"
    caplog.set_level(logging.INFO)

    await addon.requestheaders(flow)

    assert flow.response is None
    assert flow.server_conn.address == ("203.0.113.10", 443)
    assert flow.server_conn.sni == "api.example.com"
    assert flow.request.stream is True
    record = json.loads(caplog.records[-1].message)
    assert record["decision"] == "allow"
    assert record["host"] == "api.example.com"
    assert "token" not in caplog.records[-1].message
    assert "Bearer" not in caplog.records[-1].message
    assert "private request body" not in caplog.records[-1].message


@pytest.mark.asyncio
async def test_request_rejects_authority_mismatch_and_denied_resolution() -> None:
    addon = AzentsProxyAddon(_policy(), readiness_port=0, resolver=_resolver)
    mismatch = _flow(
        "https://api.example.com/",
        host_header="other.example.com",
    )

    await addon.requestheaders(mismatch)

    assert mismatch.response is not None
    assert mismatch.response.status_code == 403

    async def denied_resolver(host: str, port: int) -> tuple[str, ...]:
        del host, port
        return ("203.0.113.10", "198.51.100.10")

    denied = _flow("https://api.example.com/")
    denied_addon = AzentsProxyAddon(
        _policy(), readiness_port=0, resolver=denied_resolver
    )
    await denied_addon.requestheaders(denied)

    assert denied.response is not None
    assert denied.response.status_code == 403


@pytest.mark.asyncio
async def test_redirect_is_rechecked_before_returning_to_runtime() -> None:
    addon = AzentsProxyAddon(_policy(), readiness_port=0, resolver=_resolver)
    flow = _flow("https://api.example.com/")
    flow.response = http.Response.make(
        302,
        b"must not be retained",
        {"location": "https://outside.example.net/private?token=secret"},
    )

    await addon.responseheaders(flow)

    assert flow.response.status_code == 403
    assert flow.response.content == b""


def test_server_connection_requires_allowed_ip_before_and_after_connect() -> None:
    addon = AzentsProxyAddon(_policy(), readiness_port=0, resolver=_resolver)
    client = connection.Client(
        peername=("127.0.0.1", 40_000),
        sockname=("127.0.0.1", 8080),
    )
    server = connection.Server(address=("api.example.com", 443))
    data = ServerConnectionHookData(server=server, client=client)

    addon.server_connect(data)

    assert server.error == "upstream address is not authorized"
    server.error = None
    server.address = ("203.0.113.10", 443)
    addon.server_connect(data)
    assert server.error is None
    server.peername = ("198.51.100.10", 443)
    addon.server_connected(data)
    assert server.error == "upstream peer address is not authorized"


def test_raw_tcp_and_udp_flows_are_killed() -> None:
    addon = AzentsProxyAddon(_policy(), readiness_port=0, resolver=_resolver)
    client = connection.Client(
        peername=("127.0.0.1", 40_000),
        sockname=("127.0.0.1", 8080),
    )
    tcp_flow = tcp.TCPFlow(
        client,
        connection.Server(address=("203.0.113.10", 22)),
        live=True,
    )
    udp_flow = udp.UDPFlow(
        client,
        connection.Server(address=("203.0.113.10", 443)),
        live=True,
    )

    addon.tcp_start(tcp_flow)
    addon.udp_start(udp_flow)

    assert not tcp_flow.live
    assert not udp_flow.live


def test_tls_clienthello_requires_sni_to_match_connect_authority() -> None:
    addon = AzentsProxyAddon(_policy(), readiness_port=0, resolver=_resolver)
    client = connection.Client(
        peername=("127.0.0.1", 40_000),
        sockname=("127.0.0.1", 8080),
        state=(
            connection.ConnectionState.CAN_READ | connection.ConnectionState.CAN_WRITE
        ),
    )
    context = Context(client, Options())
    context.server.address = ("203.0.113.10", 443)
    context.server.sni = "api.example.com"
    client_hello = MagicMock(spec=tls.ClientHello)
    client_hello.sni = "other.example.com"
    data = tls.ClientHelloData(context=context, client_hello=client_hello)

    addon.tls_clienthello(data)

    assert client.state is connection.ConnectionState.CLOSED
    assert client.error == "TLS SNI does not match CONNECT authority"


def test_tls_clienthello_accepts_matching_sni() -> None:
    addon = AzentsProxyAddon(_policy(), readiness_port=0, resolver=_resolver)
    client = connection.Client(
        peername=("127.0.0.1", 40_000),
        sockname=("127.0.0.1", 8080),
        state=(
            connection.ConnectionState.CAN_READ | connection.ConnectionState.CAN_WRITE
        ),
    )
    context = Context(client, Options())
    context.server.address = ("203.0.113.10", 443)
    context.server.sni = "api.example.com"
    client_hello = MagicMock(spec=tls.ClientHello)
    client_hello.sni = "API.EXAMPLE.COM"
    data = tls.ClientHelloData(context=context, client_hello=client_hello)

    addon.tls_clienthello(data)

    assert client.state == (
        connection.ConnectionState.CAN_READ | connection.ConnectionState.CAN_WRITE
    )
    assert client.error is None


def test_tls_clienthello_accepts_absent_sni_for_ip_authority() -> None:
    addon = AzentsProxyAddon(_policy(), readiness_port=0, resolver=_resolver)
    client = connection.Client(
        peername=("127.0.0.1", 40_000),
        sockname=("127.0.0.1", 8080),
        state=(
            connection.ConnectionState.CAN_READ | connection.ConnectionState.CAN_WRITE
        ),
    )
    context = Context(client, Options())
    context.server.address = ("203.0.113.10", 443)
    context.server.sni = None
    client_hello = MagicMock(spec=tls.ClientHello)
    client_hello.sni = None
    data = tls.ClientHelloData(context=context, client_hello=client_hello)

    addon.tls_clienthello(data)

    assert client.state == (
        connection.ConnectionState.CAN_READ | connection.ConnectionState.CAN_WRITE
    )
    assert client.error is None


def test_tls_clienthello_rejects_hostname_sni_for_ip_authority() -> None:
    addon = AzentsProxyAddon(_policy(), readiness_port=0, resolver=_resolver)
    client = connection.Client(
        peername=("127.0.0.1", 40_000),
        sockname=("127.0.0.1", 8080),
        state=(
            connection.ConnectionState.CAN_READ | connection.ConnectionState.CAN_WRITE
        ),
    )
    context = Context(client, Options())
    context.server.address = ("203.0.113.10", 443)
    context.server.sni = None
    client_hello = MagicMock(spec=tls.ClientHello)
    client_hello.sni = "api.example.com"
    data = tls.ClientHelloData(context=context, client_hello=client_hello)

    addon.tls_clienthello(data)

    assert client.state is connection.ConnectionState.CLOSED
    assert client.error == "TLS SNI does not match IP CONNECT authority"


@pytest.mark.asyncio
async def test_running_addon_exposes_exact_loopback_readiness_evidence() -> None:
    addon = AzentsProxyAddon(_policy(), readiness_port=0, resolver=_resolver)
    await addon.running()
    assert addon.readiness_server is not None
    host, port = addon.readiness_server.sockets[0].getsockname()[:2]
    assert host == "127.0.0.1"

    reader, writer = await asyncio.open_connection(host, port)
    writer.write(b"GET /ready HTTP/1.1\r\nHost: localhost\r\n\r\n")
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    addon.done()

    _, raw_body = response.split(b"\r\n\r\n", maxsplit=1)
    assert json.loads(raw_body) == {
        "runtime_id": "runtime-1",
        "configuration_sequence": 4,
        "policy_digest": "d" * 64,
        "ca_fingerprint": "b" * 64,
        "artifact_digest": "c" * 64,
    }
