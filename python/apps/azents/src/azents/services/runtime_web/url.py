"""Runtime Web endpoint URL resolution contract."""

from typing import Annotated, Protocol

from fastapi import Depends


class RuntimeWebEndpointUrlResolver(Protocol):
    """Resolve a stable hostname key to its configured public URL."""

    def resolve(self, hostname_key: str) -> str | None:
        """Return a configured public URL or None when unavailable."""
        ...


class UnconfiguredRuntimeWebEndpointUrlResolver:
    """Phase 1 URL resolver before Gateway installation configuration exists."""

    def resolve(self, hostname_key: str) -> str | None:
        """Return no URL while the Gateway is unconfigured."""
        del hostname_key
        return None


def get_unconfigured_runtime_web_endpoint_url_resolver() -> (
    UnconfiguredRuntimeWebEndpointUrlResolver
):
    """Create the default unconfigured URL resolver."""
    return UnconfiguredRuntimeWebEndpointUrlResolver()


def get_runtime_web_endpoint_url_resolver(
    resolver: Annotated[
        UnconfiguredRuntimeWebEndpointUrlResolver,
        Depends(get_unconfigured_runtime_web_endpoint_url_resolver),
    ],
) -> RuntimeWebEndpointUrlResolver:
    """Return the configured Runtime Web URL resolver contract."""
    return resolver
