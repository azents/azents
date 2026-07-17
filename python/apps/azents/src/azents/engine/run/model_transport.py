"""In-memory model transport fallback state."""

import dataclasses
from typing import Literal, Protocol

ModelTransportFamily = Literal["openai_responses"]


@dataclasses.dataclass(frozen=True)
class ModelTransportKey:
    """Non-sensitive identity for one physical model transport configuration."""

    family: ModelTransportFamily
    provider: str
    provider_integration_id: str | None


class ModelTransportState(Protocol):
    """Session-owned model transport eligibility state."""

    def websocket_allowed(self, key: ModelTransportKey) -> bool:
        """Return whether WebSocket remains eligible for the transport key."""
        ...

    def mark_http_only(self, key: ModelTransportKey) -> None:
        """Keep the transport key on HTTP for the remaining state lifetime."""
        ...


class InMemoryModelTransportState:
    """Retain keyed HTTP-only fallback for one SessionRunner lifetime."""

    def __init__(self, *, websocket_enabled: bool) -> None:
        self.websocket_enabled = websocket_enabled
        self._http_only: set[ModelTransportKey] = set()

    def websocket_allowed(self, key: ModelTransportKey) -> bool:
        """Return deployment and keyed fallback eligibility."""
        return self.websocket_enabled and key not in self._http_only

    def mark_http_only(self, key: ModelTransportKey) -> None:
        """Disable WebSocket for one resolved transport key."""
        self._http_only.add(key)
