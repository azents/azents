"""Platform isolation and transport header normalization for Runtime Web."""

import dataclasses
import enum
import re
import urllib.parse
from collections.abc import Iterable, Mapping, Sequence

from azents.runtime_web_gateway.settings import RuntimeWebGatewayConfig

_ENDPOINT_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_FORBIDDEN_REQUEST_HEADERS = frozenset(
    {
        b"connection",
        b"cookie",
        b"host",
        b"keep-alive",
        b"proxy-authenticate",
        b"proxy-authorization",
        b"sec-websocket-accept",
        b"sec-websocket-extensions",
        b"sec-websocket-key",
        b"sec-websocket-version",
        b"te",
        b"trailer",
        b"transfer-encoding",
        b"upgrade",
    }
)
_FORBIDDEN_RESPONSE_HEADERS = frozenset(
    {
        b"connection",
        b"keep-alive",
        b"proxy-authenticate",
        b"proxy-authorization",
        b"sec-websocket-accept",
        b"sec-websocket-extensions",
        b"sec-websocket-key",
        b"sec-websocket-version",
        b"te",
        b"trailer",
        b"transfer-encoding",
        b"upgrade",
    }
)
_PLATFORM_COOKIE_PREFIXES = (
    "__host-azents-",
    "__http-azents-",
    "az-token",
    "az-refresh",
)
_SERVICE_WORKER_DESTINATIONS = frozenset({"serviceworker", "sharedworker"})


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


def reject_service_worker_request(headers: Mapping[str, str]) -> None:
    """Reject service-worker script or update traffic before cache/proxy work."""
    destination = headers.get("Sec-Fetch-Dest", "").lower()
    service_worker = headers.get("Service-Worker", "").lower()
    if destination in _SERVICE_WORKER_DESTINATIONS or service_worker == "script":
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)


def normalize_request_headers(
    headers: Sequence[tuple[bytes, bytes]],
    *,
    port: int,
    target_origin: str,
    maximum_bytes: int,
) -> tuple[tuple[bytes, bytes], ...]:
    """Strip platform and hop-by-hop fields while retaining ordered app headers."""
    size = sum(len(name) + len(value) + 4 for name, value in headers)
    if size > maximum_bytes:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.HEADER_TOO_LARGE)
    output: list[tuple[bytes, bytes]] = [(b"host", f"localhost:{port}".encode())]
    for name, value in headers:
        lowered = name.lower()
        if lowered in _FORBIDDEN_REQUEST_HEADERS:
            continue
        if lowered == b"authorization":
            output.append((lowered, value))
            continue
        if lowered == b"origin":
            if _http_origin(value.decode("latin-1")) == target_origin:
                output.append((lowered, f"http://localhost:{port}".encode()))
            else:
                output.append((lowered, value))
            continue
        if lowered == b"referer":
            output.append(
                (
                    lowered,
                    _normalized_referer(value, target_origin=target_origin, port=port),
                )
            )
            continue
        output.append((lowered, value))
    return tuple(output)


def normalize_response_headers(
    headers: Iterable[tuple[bytes, bytes]],
    *,
    target_origin: str,
    port: int,
) -> tuple[tuple[str, str], ...]:
    """Preserve application policy while normalizing transport and local URLs."""
    output: list[tuple[str, str]] = []
    for name, value in headers:
        lowered = name.lower()
        if lowered in _FORBIDDEN_RESPONSE_HEADERS:
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


def _http_origin(value: str) -> str | None:
    """Return an HTTP origin for local rewriting, or preserve opaque values."""
    try:
        parsed = urllib.parse.urlparse(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None
    default_port = 443 if parsed.scheme == "https" else 80
    if port in {None, default_port}:
        return f"{parsed.scheme}://{hostname.lower()}"
    return f"{parsed.scheme}://{hostname.lower()}:{port}"


def _reserved_set_cookie(value: bytes) -> bool:
    name = value.split(b"=", 1)[0].strip().decode("latin-1").lower()
    return any(name.startswith(prefix) for prefix in _PLATFORM_COOKIE_PREFIXES)


def _normalize_application_cookie(value: str) -> str:
    parts = [part.strip() for part in value.split(";")]
    normalized = [
        part
        for part in parts
        if not part.lower().startswith("domain=localhost")
        and not part.lower().startswith("domain=127.0.0.1")
    ]
    return "; ".join(normalized)


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


def _normalized_referer(value: bytes, *, target_origin: str, port: int) -> bytes:
    try:
        text = value.decode("latin-1")
        parsed = urllib.parse.urlparse(text)
        if _http_origin(f"{parsed.scheme}://{parsed.netloc}") != target_origin:
            return value
        return urllib.parse.urlunparse(
            ("http", f"localhost:{port}", parsed.path, "", parsed.query, "")
        ).encode("latin-1")
    except ValueError:
        return value
