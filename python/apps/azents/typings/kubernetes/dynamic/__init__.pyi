"""kubernetes.dynamic — DynamicClient resource iterator type extensions."""

from collections.abc import Iterator
from typing import Any

from kubernetes.client import ApiClient

class _Resource:
    """Resource metadata yielded when iterating over DynamicClient.resources."""

    group_version: str
    kind: str
    namespaced: bool
    def get(self, **kwargs: Any) -> Any: ...

class _ResourceSearch:
    """DynamicClient.resources discovery with lookup and iteration support."""
    def get(self, *, api_version: str, kind: str) -> _ResourceApi: ...
    def __iter__(self) -> Iterator[_Resource]: ...

class _ResourceApi:
    """API handle for one api_version and kind."""
    def get(self, **kwargs: Any) -> Any: ...
    def server_side_apply(self, **kwargs: Any) -> Any: ...
    def delete(self, **kwargs: Any) -> Any: ...

class DynamicClient:
    def __init__(self, client: ApiClient) -> None: ...
    @property
    def resources(self) -> _ResourceSearch: ...
