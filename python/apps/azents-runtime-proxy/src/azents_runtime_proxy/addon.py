"""Mitmproxy addon enforcing the canonical Azents proxy policy."""

import asyncio
import dataclasses
import ipaddress
import json
import logging
import socket
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from urllib.parse import urlsplit

from mitmproxy import connection, http, tcp, tls, udp
from mitmproxy.proxy import server_hooks

from azents_runtime_proxy.policy import (
    InvalidProxyPolicy,
    ProxyPolicy,
    canonical_host,
)

_LOGGER = logging.getLogger(__name__)
type AddressResolver = Callable[[str, int], Awaitable[Sequence[str]]]
_READINESS_REQUEST_LIMIT = 8_192


@dataclasses.dataclass(frozen=True)
class ProxyDecision:
    """Bounded redacted proxy decision record."""

    decision: str
    host: str
    port: int
    selected_ip_class: str | None
    protocol_class: str
    reason: str


class AzentsProxyAddon:
    """Enforce hostname, DNS result, selected IP, redirect, and protocol policy."""

    def __init__(
        self,
        policy: ProxyPolicy,
        *,
        readiness_port: int,
        resolver: AddressResolver | None = None,
    ) -> None:
        """Initialize one Runtime-bound addon."""
        self.policy = policy
        self.readiness_port = readiness_port
        self.resolver = resolver or resolve_addresses
        self.readiness_server: asyncio.Server | None = None

    async def running(self) -> None:
        """Expose this running addon's exact evidence on loopback only."""
        self.readiness_server = await asyncio.start_server(
            self._handle_readiness,
            host="127.0.0.1",
            port=self.readiness_port,
            limit=_READINESS_REQUEST_LIMIT,
        )

    def done(self) -> None:
        """Stop accepting readiness connections during addon shutdown."""
        if self.readiness_server is not None:
            self.readiness_server.close()

    def tls_clienthello(self, data: tls.ClientHelloData) -> None:
        """Fail the client handshake when CONNECT authority and TLS SNI differ."""
        expected_sni = data.context.server.sni
        sni = data.client_hello.sni
        try:
            if expected_sni is None:
                if sni is not None:
                    raise InvalidProxyPolicy(
                        "TLS SNI does not match IP CONNECT authority"
                    )
                return
            if sni is None:
                raise InvalidProxyPolicy("TLS SNI is missing")
            if canonical_host(sni) != canonical_host(expected_sni):
                raise InvalidProxyPolicy("TLS SNI does not match CONNECT authority")
        except InvalidProxyPolicy as error:
            data.context.client.error = str(error)
            data.context.client.state = connection.ConnectionState.CLOSED

    async def http_connect(self, flow: http.HTTPFlow) -> None:
        """Authorize and pin a CONNECT tunnel before its TLS handshake."""
        await self._authorize_and_pin(flow)

    async def requestheaders(self, flow: http.HTTPFlow) -> None:
        """Authorize authority before resolution and pin an allowed selected IP."""
        await self._authorize_and_pin(flow)

    async def _authorize_and_pin(self, flow: http.HTTPFlow) -> None:
        try:
            host = self._request_host(flow)
            port = flow.request.port
            addresses = await self._addresses(host, port)
            selected = self.policy.authorize_addresses(addresses)[0]
            authority = flow.request.authority
            host_header = flow.request.host_header
            flow.request.host = selected
            flow.request.authority = authority
            flow.request.host_header = host_header
            flow.server_conn.address = (selected, port)
            flow.server_conn.sni = None if _is_ip_address(host) else host
            flow.request.stream = True
            self._record(
                ProxyDecision(
                    decision="allow",
                    host=host,
                    port=port,
                    selected_ip_class=_ip_class(selected),
                    protocol_class=_protocol_class(flow.request),
                    reason="policy_match",
                )
            )
        except (InvalidProxyPolicy, ValueError) as error:
            self._deny_http(flow, reason=str(error))

    async def responseheaders(self, flow: http.HTTPFlow) -> None:
        """Reject redirects whose destination cannot satisfy current policy."""
        if flow.response is None:
            return
        flow.response.stream = True
        location = flow.response.headers.get("location")
        if not location:
            return
        target = urlsplit(location)
        if not target.hostname:
            return
        try:
            host = self.policy.authorize_host(target.hostname)
            port = target.port or (443 if target.scheme == "https" else 80)
            self.policy.authorize_addresses(await self._addresses(host, port))
        except (InvalidProxyPolicy, ValueError) as error:
            self._deny_http(flow, reason=f"redirect_denied:{error}")

    def server_connect(self, data: server_hooks.ServerConnectionHookData) -> None:
        """Reject any upstream connection that is not pinned to an allowed IP."""
        address = data.server.address
        if address is None:
            data.server.error = "upstream address is missing"
            return
        try:
            self.policy.authorize_address(address[0])
        except InvalidProxyPolicy, ValueError:
            data.server.error = "upstream address is not authorized"
            return
        if data.server.sni is not None and _is_ip_address(data.server.sni):
            try:
                data.server.sni = (
                    canonical_host(data.client.sni)
                    if data.client.sni is not None
                    else None
                )
            except InvalidProxyPolicy:
                data.server.error = "upstream SNI is not authorized"

    def server_connected(self, data: server_hooks.ServerConnectionHookData) -> None:
        """Verify the selected peer address after connection establishment."""
        peername = data.server.peername
        if peername is None:
            data.server.error = "upstream peer address is missing"
            return
        try:
            self.policy.authorize_address(peername[0])
        except InvalidProxyPolicy, ValueError:
            data.server.error = "upstream peer address is not authorized"

    def tcp_start(self, flow: tcp.TCPFlow) -> None:
        """Deny raw TCP forwarding."""
        flow.kill()

    def udp_start(self, flow: udp.UDPFlow) -> None:
        """Deny UDP and QUIC forwarding."""
        flow.kill()

    async def _addresses(self, host: str, port: int) -> Sequence[str]:
        if _is_ip_address(host):
            return (host,)
        return await self.resolver(host, port)

    def _request_host(self, flow: http.HTTPFlow) -> str:
        request = flow.request
        if _is_ip_address(request.host) and flow.server_conn.sni is not None:
            pinned_address = flow.server_conn.address
            if pinned_address is None or request.host != pinned_address[0]:
                raise InvalidProxyPolicy(
                    "request destination does not match pinned upstream"
                )
            host = self.policy.authorize_host(flow.server_conn.sni)
        else:
            host = self.policy.authorize_host(request.host)
        authority = request.host_header or request.authority
        if authority:
            authority_host = urlsplit(f"//{authority}").hostname
            if authority_host is None or canonical_host(authority_host) != host:
                raise InvalidProxyPolicy("request authority does not match host")
        return host

    async def _handle_readiness(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await reader.readline()
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
            if request_line != b"GET /ready HTTP/1.1\r\n":
                writer.write(
                    b"HTTP/1.1 404 Not Found\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )
            else:
                body = json.dumps(
                    {
                        "runtime_id": self.policy.runtime_id,
                        "configuration_sequence": self.policy.configuration_sequence,
                        "policy_digest": self.policy.digest,
                        "ca_fingerprint": self.policy.ca_fingerprint,
                        "artifact_digest": self.policy.artifact_digest,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\n".encode()
                    + b"Connection: close\r\n\r\n"
                    + body
                )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    def _deny_http(self, flow: http.HTTPFlow, *, reason: str) -> None:
        request = flow.request
        try:
            host = canonical_host(request.host)
        except InvalidProxyPolicy:
            host = "invalid"
        flow.response = http.Response.make(
            403,
            b"",
            {"content-type": "text/plain", "cache-control": "no-store"},
        )
        self._record(
            ProxyDecision(
                decision="deny",
                host=host,
                port=request.port,
                selected_ip_class=None,
                protocol_class=_protocol_class(request),
                reason=reason[:128],
            )
        )

    def _record(self, decision: ProxyDecision) -> None:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "runtime_id": self.policy.runtime_id,
            "decision": decision.decision,
            "host": decision.host,
            "port": decision.port,
            "selected_ip_class": decision.selected_ip_class,
            "protocol_class": decision.protocol_class,
            "policy_digest": self.policy.digest,
            "reason": decision.reason,
        }
        _LOGGER.info(json.dumps(payload, sort_keys=True, separators=(",", ":")))


async def resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    """Resolve all A and AAAA candidates through the proxy Pod resolver."""
    loop = asyncio.get_running_loop()
    results = await loop.getaddrinfo(
        host,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    return tuple(
        sorted(
            {str(ipaddress.ip_address(item[4][0])) for item in results},
            key=lambda item: (
                ipaddress.ip_address(item).version,
                ipaddress.ip_address(item).packed,
            ),
        )
    )


def _protocol_class(request: http.Request) -> str:
    if request.method == "CONNECT":
        return "connect"
    if request.scheme == "https":
        return "https"
    return "http"


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _ip_class(address: str) -> str:
    candidate = ipaddress.ip_address(address)
    if candidate.is_loopback:
        return "loopback"
    if candidate.is_private:
        return "private"
    if candidate.is_link_local:
        return "link_local"
    if candidate.is_global:
        return "global"
    return "special"
