"""kubernetes_asyncio.client 타입 스텁.

kubernetes_asyncio는 타입 스텁을 제공하지 않으므로
프로젝트에서 사용하는 API를 직접 선언한다.

Agent Home은 lightkube로 마이그레이션 완료.
여기에는 exec 도구(WsApiClient) + 인증에 필요한 최소 타입만 유지한다.
"""

from collections.abc import Callable, Coroutine
from typing import Any

from aiohttp import ClientSession

# ── Configuration / ApiClient ──────────────────────────

class Configuration:
    host: str
    proxy: str | None
    proxy_headers: dict[str, str] | None
    ssl_ca_cert: str | None
    tls_server_name: str | None
    api_key: dict[str, str]
    refresh_api_key_hook: Callable[[ApiClient], None] | None
    def __init__(self) -> None: ...

class RESTClientObject:
    pool_manager: ClientSession

class ApiClient:
    configuration: Configuration
    rest_client: RESTClientObject
    def __init__(self, configuration: Configuration | None = None) -> None: ...
    async def close(self) -> None: ...

# ── CoreV1Api (exec + version 전용) ─────────────────────

class CoreV1Api:
    def __init__(self, api_client: ApiClient | None = None) -> None: ...

    # exec — WsApiClient를 통해 호출
    def connect_get_namespaced_pod_exec(
        self, **kwargs: Any
    ) -> Coroutine[Any, Any, Any]: ...
    def connect_post_namespaced_pod_exec(
        self, **kwargs: Any
    ) -> Coroutine[Any, Any, Any]: ...

# ── VersionApi ────────────────────────────────────────

class VersionInfo:
    git_version: str

class VersionApi:
    def __init__(self, api_client: ApiClient | None = None) -> None: ...
    def get_code(
        self,
    ) -> Coroutine[Any, Any, VersionInfo]: ...
