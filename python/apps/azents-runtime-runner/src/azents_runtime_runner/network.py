"""Provider-owned child-process network environment preparation."""

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

_PROXY_INPUT_ENV = "AZ_RUNTIME_RUNNER_HTTP_PROXY"
_PROXY_ENVIRONMENT_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
)


def prepare_runner_network_environment() -> Mapping[str, str]:
    """Project one Provider-owned HTTP proxy only into child operations."""
    value = os.environ.get(_PROXY_INPUT_ENV)
    if value is None:
        return {}
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname is None
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("Runner HTTP proxy input is invalid")
    if not 1 <= parsed.port <= 65_535:
        raise RuntimeError("Runner HTTP proxy port is invalid")
    canonical = f"http://{parsed.hostname}:{parsed.port}"
    if value != canonical:
        raise RuntimeError("Runner HTTP proxy input is not canonical")
    return {name: canonical for name in _PROXY_ENVIRONMENT_NAMES}
