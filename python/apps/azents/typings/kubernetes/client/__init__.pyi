"""kubernetes.client — Configuration/ApiClient/CoreV1Api 타입 보강."""

from collections.abc import Callable
from typing import Any

class Configuration:
    host: str
    proxy: str | None
    ssl_ca_cert: str | None
    api_key: dict[str, str]
    refresh_api_key_hook: Callable[[ApiClient], None] | None
    def __init__(self) -> None: ...

class ApiClient:
    configuration: Configuration
    def __init__(self, configuration: Configuration | None = None) -> None: ...
    def close(self) -> None: ...

class CoreV1Api:
    def __init__(self, api_client: ApiClient | None = None) -> None: ...
    def read_namespaced_pod_log(self, **kwargs: Any) -> str: ...
    def connect_get_namespaced_pod_exec(self, **kwargs: Any) -> str: ...

class VersionInfo:
    git_version: str

class VersionApi:
    def __init__(self, api_client: ApiClient | None = None) -> None: ...
    def get_code(self) -> VersionInfo: ...
