"""kubernetes_asyncio.stream — WebSocket 기반 exec/attach 스트리밍 API 타입 보강.

WsApiClient는 ApiClient를 상속하며 WebSocket을 통한 exec을 지원한다.
"""

from kubernetes_asyncio.client import ApiClient, Configuration

class WsApiClient(ApiClient):
    heartbeat: float | None
    def __init__(self, configuration: Configuration | None = None) -> None: ...
    async def close(self) -> None: ...
