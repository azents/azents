"""Pure browser, origin, header, and response policy for Runtime Web."""

import dataclasses
import enum
import re
import urllib.parse
from collections.abc import Iterable, Mapping, Sequence

from azents.runtime_web_gateway.settings import RuntimeWebGatewayConfig

_ENDPOINT_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_CHROMIUM_BRAND = re.compile(r'"Chromium";v="(?P<version>[0-9]+)"')
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
        b"access-control-allow-credentials",
        b"access-control-allow-headers",
        b"access-control-allow-methods",
        b"access-control-allow-origin",
        b"access-control-expose-headers",
        b"access-control-max-age",
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
_CORS_REQUEST_HEADERS = frozenset(
    {
        "accept",
        "accept-language",
        "authorization",
        "content-language",
        "content-type",
        "range",
        "x-requested-with",
    }
)
_CORS_METHODS = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"})
_SERVICE_WORKER_DESTINATIONS = frozenset({"serviceworker", "sharedworker"})


class RuntimeWebPolicyCode(enum.StrEnum):
    """Bounded public Gateway policy outcome."""

    BAD_REQUEST = "bad_request"
    FORBIDDEN = "forbidden"
    HEADER_TOO_LARGE = "header_too_large"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    UPGRADE_REQUIRED = "upgrade_required"


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


@dataclasses.dataclass(frozen=True)
class RuntimeWebCorsDecision:
    """Validated CORS source and response fields."""

    origin: str | None
    headers: tuple[tuple[str, str], ...]


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


def require_supported_browser_user_agent(
    headers: Mapping[str, str],
    *,
    config: RuntimeWebGatewayConfig,
) -> str:
    """Resolve the configured Chromium profile from its User-Agent version."""
    user_agent = headers.get("User-Agent")
    match = (
        None
        if user_agent is None
        else re.search(r"(?:Chrome|Chromium)/([0-9]+)", user_agent)
    )
    if match is None:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.UPGRADE_REQUIRED)
    version = int(match.group(1))
    if not config.chromium_min_version <= version <= config.chromium_max_version:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.UPGRADE_REQUIRED)
    return f"chromium-{version}"


def require_admitted_browser(
    headers: Mapping[str, str],
    *,
    config: RuntimeWebGatewayConfig,
) -> str:
    """Require the approved Chromium prefix-enforcement evidence."""
    sec_ch_ua = headers.get("Sec-CH-UA")
    user_agent = headers.get("User-Agent")
    fetch_site = headers.get("Sec-Fetch-Site")
    fetch_mode = headers.get("Sec-Fetch-Mode")
    fetch_dest = headers.get("Sec-Fetch-Dest")
    if (
        sec_ch_ua is None
        or user_agent is None
        or fetch_site is None
        or fetch_mode is None
        or fetch_dest is None
    ):
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.UPGRADE_REQUIRED)
    match = _CHROMIUM_BRAND.search(sec_ch_ua)
    if match is None:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.UPGRADE_REQUIRED)
    browser_profile = require_supported_browser_user_agent(headers, config=config)
    client_hint_version = int(match.group("version"))
    if browser_profile != f"chromium-{client_hint_version}":
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.UPGRADE_REQUIRED)
    if fetch_site not in {"same-origin", "same-site", "cross-site", "none"}:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)
    return browser_profile


def evaluate_actual_origin(
    *,
    origin: str | None,
    fetch_site: str | None,
    fetch_mode: str | None,
    method: str,
    target_origin: str,
    source_origins: frozenset[str],
) -> RuntimeWebCorsDecision:
    """Authorize same-target or same-root credentialed browser traffic."""
    normalized_method = method.upper()
    if origin is None:
        if normalized_method in {"GET", "HEAD"} and fetch_mode == "navigate":
            return RuntimeWebCorsDecision(origin=None, headers=())
        if fetch_site == "same-origin":
            return RuntimeWebCorsDecision(origin=None, headers=())
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)
    canonical = canonical_origin(origin)
    if canonical == target_origin:
        return RuntimeWebCorsDecision(origin=canonical, headers=())
    if canonical not in source_origins:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)
    return RuntimeWebCorsDecision(
        origin=canonical,
        headers=_cors_response_headers(canonical),
    )


def evaluate_preflight(
    *,
    origin: str,
    requested_method: str,
    requested_headers: str | None,
    source_origins: frozenset[str],
) -> RuntimeWebCorsDecision:
    """Validate one structural same-root CORS preflight locally."""
    canonical = canonical_origin(origin)
    if canonical not in source_origins:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)
    method = requested_method.upper()
    if method not in _CORS_METHODS:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.METHOD_NOT_ALLOWED)
    requested = (
        frozenset(
            item.strip().lower()
            for item in requested_headers.split(",")
            if item.strip()
        )
        if requested_headers is not None
        else frozenset()
    )
    if not requested.issubset(_CORS_REQUEST_HEADERS):
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)
    headers = list(_cors_response_headers(canonical))
    headers.extend(
        [
            ("Access-Control-Allow-Methods", method),
            ("Access-Control-Max-Age", "600"),
        ]
    )
    if requested:
        headers.append(("Access-Control-Allow-Headers", ", ".join(sorted(requested))))
    return RuntimeWebCorsDecision(origin=canonical, headers=tuple(headers))


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
            if canonical_origin(value.decode("ascii")) == target_origin:
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
    config: RuntimeWebGatewayConfig,
    cors: RuntimeWebCorsDecision,
    target_origin: str,
    port: int,
) -> tuple[tuple[str, str], ...]:
    """Replace upstream browser security, CORS, cache, and reserved cookie fields."""
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
    output.extend(cors.headers)
    output.extend(
        [
            ("Cache-Control", "no-store"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Frame-Options", "DENY"),
            ("Cross-Origin-Opener-Policy", "same-origin"),
            ("Permissions-Policy", config.permissions_policy),
        ]
    )
    return tuple(output)


def canonical_origin(value: str) -> str:
    """Return one exact canonical HTTP origin."""
    parsed = urllib.parse.urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)
    default_port = 443 if parsed.scheme == "https" else 80
    if parsed.port in {None, default_port}:
        return f"{parsed.scheme}://{parsed.hostname.lower()}"
    return f"{parsed.scheme}://{parsed.hostname.lower()}:{parsed.port}"


def _cors_response_headers(origin: str) -> tuple[tuple[str, str], ...]:
    return (
        ("Access-Control-Allow-Origin", origin),
        ("Access-Control-Allow-Credentials", "true"),
        ("Vary", "Origin"),
    )


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
        text = value.decode("ascii")
        parsed = urllib.parse.urlparse(text)
        if canonical_origin(f"{parsed.scheme}://{parsed.netloc}") != target_origin:
            return value
        return urllib.parse.urlunparse(
            ("http", f"localhost:{port}", parsed.path, "", parsed.query, "")
        ).encode()
    except UnicodeDecodeError, ValueError, RuntimeWebPolicyError:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN) from None
