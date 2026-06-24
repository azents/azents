"""aiodocker 타입 stub.

aiodocker 0.x 는 type stub 을 제공하지 않아 strict pyright 가 import 자체와
모든 멤버 호출을 unknown 으로 분류한다. 이 stub 은 azents 의 Docker provider
코드가 실제로 사용하는 멤버만 정의 — aiodocker 의 전체 API 가
아님. 새 멤버를 쓰게 되면 추가한다.

azents Docker runtime 경로에서 필요한 최소 surface 만 둔다.
"""

from typing import Any

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
    ) -> list[dict[str, Any]]: ...
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
