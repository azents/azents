"""Platform isolation and transport header normalization for Runtime Web."""

import dataclasses
import enum
import re
import urllib.parse
from collections.abc import Iterable, Sequence

from azents.runtime_web_gateway.settings import RuntimeWebGatewayConfig

_ENDPOINT_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_HOP_HEADERS = frozenset(
    {
        b"connection",
        b"keep-alive",
        b"proxy-authenticate",
        b"proxy-authorization",
        b"proxy-connection",
        b"te",
        b"trailer",
        b"transfer-encoding",
        b"upgrade",
    }
)
_WEBSOCKET_HANDSHAKE_HEADERS = frozenset(
    {
        b"sec-websocket-accept",
        b"sec-websocket-extensions",
        b"sec-websocket-key",
        b"sec-websocket-version",
    }
)
_PLATFORM_COOKIE_NAMES = frozenset(
    {
        b"__Http-Azents-Runtime-Web",
        b"__Host-Azents-Runtime-Web-Broker-Binding",
        b"__Host-Azents-Runtime-Web-Binding",
        b"__Host-Azents-Access",
        b"__Host-Azents-Refresh",
        b"__Host-Azents-Access-Expires-At",
        b"az-token",
        b"az-refresh",
        b"az-token-expires-at",
    }
)


class RuntimeWebPolicyCode(enum.StrEnum):
    """Bounded public Gateway policy outcome."""

    BAD_REQUEST = "bad_request"
    FORBIDDEN = "forbidden"
    HEADER_TOO_LARGE = "header_too_large"


class RuntimeWebPolicyError(ValueError):
    """A request failed before any Runtime traffic."""

    def __init__(self, code: RuntimeWebPolicyCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclasses.dataclass(frozen=True)
class RuntimeWebTarget:
    """Host-derived public target."""

    endpoint_label: str | None
    broker: bool


def parse_target_host(
    host_header: str,
    *,
    config: RuntimeWebGatewayConfig,
) -> RuntimeWebTarget:
    """Parse one exact broker or endpoint Host without suffix ambiguity."""
    if (
        not host_header
        or "," in host_header
        or any(character in host_header for character in "/?#@")
    ):
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST)
    try:
        parsed = urllib.parse.urlsplit(f"//{host_header}")
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST) from None
    if (
        hostname is None
        or any(character.isupper() for character in host_header)
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
    ):
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST)
    broker_host = urllib.parse.urlparse(config.broker_origin).hostname
    if hostname == broker_host:
        return RuntimeWebTarget(endpoint_label=None, broker=True)
    suffix = f".{config.service_suffix}"
    if not hostname.endswith(suffix):
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)
    label = hostname[: -len(suffix)]
    if "." in label or _ENDPOINT_LABEL.fullmatch(label) is None:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)
    return RuntimeWebTarget(endpoint_label=label, broker=False)


def normalize_request_headers(
    headers: Sequence[tuple[bytes, bytes]],
    *,
    port: int,
    websocket: bool,
    maximum_bytes: int,
) -> tuple[tuple[bytes, bytes], ...]:
    """Strip platform and hop-by-hop fields while retaining ordered app headers."""
    size = sum(len(name) + len(value) + 4 for name, value in headers)
    if size > maximum_bytes:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.HEADER_TOO_LARGE)
    consumed = _HOP_HEADERS | _connection_headers(headers) | {b"host"}
    if websocket:
        consumed |= _WEBSOCKET_HANDSHAKE_HEADERS | {b"content-length"}
    output: list[tuple[bytes, bytes]] = [(b"host", f"localhost:{port}".encode())]
    for name, value in headers:
        lowered = name.lower()
        if lowered in consumed:
            continue
        if lowered == b"cookie":
            pairs = (
                pair.strip()
                for pair in value.split(b";")
                if pair.split(b"=", 1)[0].strip() not in _PLATFORM_COOKIE_NAMES
            )
            application_cookie = b"; ".join(pair for pair in pairs if pair)
            if application_cookie:
                output.append((name, application_cookie))
            continue
        output.append((name, value))
    return tuple(output)


def normalize_response_headers(
    headers: Iterable[tuple[bytes, bytes]],
    *,
    target_origin: str,
    port: int,
    websocket: bool,
) -> tuple[tuple[str, str], ...]:
    """Preserve application policy while normalizing transport and local URLs."""
    ordered = tuple(headers)
    consumed = _HOP_HEADERS | _connection_headers(ordered)
    if websocket:
        consumed |= _WEBSOCKET_HANDSHAKE_HEADERS | {
            b"sec-websocket-protocol",
            b"content-length",
        }
    output: list[tuple[str, str]] = []
    for name, value in ordered:
        lowered = name.lower()
        if lowered in consumed:
            continue
        if lowered == b"set-cookie" and _reserved_set_cookie(value):
            continue
        text = value.decode("latin-1")
        if lowered == b"set-cookie":
            text = _normalize_application_cookie(text)
        elif lowered == b"location":
            text = _normalize_location(
                text,
                target_origin=target_origin,
                port=port,
            )
        output.append((name.decode("latin-1"), text))
    return tuple(output)


def _connection_headers(
    headers: Sequence[tuple[bytes, bytes]],
) -> frozenset[bytes]:
    """Gather connection-local field names across all Connection headers."""
    return frozenset(
        token.strip().lower()
        for name, value in headers
        if name.lower() == b"connection"
        for token in value.split(b",")
        if token.strip()
    )


def _reserved_set_cookie(value: bytes) -> bool:
    return value.split(b"=", 1)[0].strip() in _PLATFORM_COOKIE_NAMES


def _normalize_application_cookie(value: str) -> str:
    parts = [part.strip() for part in value.split(";")]
    normalized = [
        part
        for part in parts
        if not (
            part.partition("=")[0].strip().lower() == "domain"
            and part.partition("=")[2].strip().lower().lstrip(".")
            in {"localhost", "127.0.0.1"}
        )
    ]
    return "; ".join(normalized) if len(normalized) != len(parts) else value


def _normalize_location(
    value: str,
    *,
    target_origin: str,
    port: int,
) -> str:
    parsed = urllib.parse.urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    if (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"localhost", "127.0.0.1"}
        and parsed.port == port
    ):
        public = urllib.parse.urlparse(target_origin)
        return urllib.parse.urlunparse(
            (
                public.scheme,
                public.netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )
    return value
