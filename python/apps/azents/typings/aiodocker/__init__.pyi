"""Type stubs for aiodocker.

aiodocker 0.x does not provide type stubs, so strict type checking classifies
imports and member calls as unknown. Declare the minimal surface used by the
Azents Docker Runtime provider and extend it when new members are needed.
"""

from typing import Any, List

from aiodocker.containers import DockerContainer
from aiodocker.exceptions import DockerError

__all__ = ["Docker", "DockerContainer", "DockerError"]

class _Containers:
    def container(self, container_id: str) -> DockerContainer: ...
    async def get(self, container_id: str) -> DockerContainer: ...
    async def create(
        self,
        *,
        config: dict[str, Any],
        name: str,
    ) -> DockerContainer: ...

class _Networks:
    async def list(  # noqa: A003
        self,
        *,
        filters: dict[str, Any],
    ) -> List[dict[str, Any]]: ...
    async def create(self, config: dict[str, Any]) -> None: ...

class _Images:
    async def inspect(self, image: str) -> dict[str, Any]: ...
    async def pull(self, image: str) -> None: ...
    async def push(
        self,
        name: str,
        *,
        tag: str | None = ...,
    ) -> list[dict[str, Any]]: ...
    async def delete(
        self,
        name: str,
        *,
        force: bool = ...,
    ) -> list[dict[str, Any]]: ...

class Docker:
    containers: _Containers
    networks: _Networks
    images: _Images

    def __init__(self, url: str | None = ...) -> None: ...
    async def close(self) -> None: ...
