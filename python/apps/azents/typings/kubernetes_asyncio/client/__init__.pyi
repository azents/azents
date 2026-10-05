"""Type stubs for the kubernetes_asyncio.client surface used by Azents.

Declare exec, authentication, and Provider credential bootstrap operations.
Agent Home operations use lightkube.
"""

from collections.abc import Callable, Coroutine
from typing import Any

from aiohttp import ClientSession
from kubernetes_asyncio.client.models.v1_secret import V1Secret

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

# ── CoreV1Api (exec and Provider credential bootstrap) ──

class CoreV1Api:
    def __init__(self, api_client: ApiClient | None = None) -> None: ...
    def read_namespaced_secret(
        self, name: str, namespace: str, **kwargs: Any
    ) -> Coroutine[Any, Any, V1Secret]: ...
    def create_namespaced_secret(
        self, namespace: str, body: V1Secret, **kwargs: Any
    ) -> Coroutine[Any, Any, V1Secret]: ...
    def patch_namespaced_secret(
        self, name: str, namespace: str, body: dict[str, object], **kwargs: Any
    ) -> Coroutine[Any, Any, V1Secret]: ...

    # Exec operations are called through WsApiClient.
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
