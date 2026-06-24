"""aiodocker.containers stub — azents 사용 멤버만."""

from types import TracebackType
from typing import Any

class _ExecMessage:
    """exec stream 의 한 메시지 — stream id 와 payload."""

    stream: int
    data: bytes

class _ExecStream:
    async def __aenter__(self) -> "_ExecStream": ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...
    async def read_out(self) -> _ExecMessage | None: ...

class _Exec:
    def start(self, *, detach: bool = ...) -> _ExecStream: ...
    async def inspect(self) -> dict[str, Any]: ...

class DockerContainer:
    """aiodocker DockerContainer — azents runtime provider 사용 멤버만."""

    async def show(self) -> dict[str, Any]: ...
    async def start(self) -> None: ...
    async def kill(self) -> None: ...
    async def delete(self, *, force: bool = ...) -> None: ...
    async def commit(
        self,
        *,
        repository: str | None = ...,
        tag: str | None = ...,
        message: str | None = ...,
        author: str | None = ...,
    ) -> dict[str, Any]: ...
    async def exec(  # noqa: A003
        self,
        *,
        cmd: list[str],
        stdout: bool = ...,
        stderr: bool = ...,
        tty: bool = ...,
    ) -> _Exec: ...
