"""Typed gateway authorization and Engine transport models."""

import dataclasses
from collections.abc import AsyncIterator, Callable, Mapping


@dataclasses.dataclass(frozen=True)
class AuthorizedEngineRequest:
    """One fully validated request that may reach the private Engine socket."""

    operation: str
    correlation_id: str
    method: str
    path: str
    query: tuple[tuple[str, str], ...]
    headers: Mapping[str, str]
    body: bytes
    required_containers: tuple[str, ...]
    required_volumes: tuple[str, ...]
    required_networks: tuple[str, ...]
    requested_pids_limit: int | None


@dataclasses.dataclass(frozen=True)
class EngineResponse:
    """Buffered response returned from the private Engine."""

    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclasses.dataclass(frozen=True)
class EngineStreamResponse:
    """Streaming response returned from one explicitly streaming operation."""

    status: int
    headers: Mapping[str, str]
    body: AsyncIterator[bytes]
    release: Callable[[], None]


@dataclasses.dataclass(frozen=True)
class EngineContainerUsage:
    """Current Runtime-owned nested-container resource usage."""

    count: int
    pids_limit: int


class GatewayAuthorizationDenied(ValueError):
    """Docker-compatible request is outside the closed policy surface."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
