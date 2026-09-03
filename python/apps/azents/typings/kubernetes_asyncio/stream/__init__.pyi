"""kubernetes_asyncio.stream — WebSocket exec/attach streaming type extensions.

WsApiClient inherits from ApiClient and supports exec over WebSockets.
"""

from kubernetes_asyncio.client import ApiClient, Configuration

class WsApiClient(ApiClient):
    heartbeat: float | None
    def __init__(self, configuration: Configuration | None = None) -> None: ...
    async def close(self) -> None: ...
