"""kubernetes.dynamic — DynamicClient의 resources 반복자 타입 보강."""

from collections.abc import Iterator
from typing import Any

from kubernetes.client import ApiClient

class _Resource:
    """DynamicClient.resources 반복 시 yield되는 리소스 메타데이터."""

    group_version: str
    kind: str
    namespaced: bool
    def get(self, **kwargs: Any) -> Any: ...

class _ResourceSearch:
    """DynamicClient.resources — get/search와 반복을 지원하는 discoverer."""
    def get(self, *, api_version: str, kind: str) -> _ResourceApi: ...
    def __iter__(self) -> Iterator[_Resource]: ...

class _ResourceApi:
    """특정 api_version+kind에 대한 API 핸들."""
    def get(self, **kwargs: Any) -> Any: ...
    def server_side_apply(self, **kwargs: Any) -> Any: ...
    def delete(self, **kwargs: Any) -> Any: ...

class DynamicClient:
    def __init__(self, client: ApiClient) -> None: ...
    @property
    def resources(self) -> _ResourceSearch: ...
