"""aiodocker.containers stub — only members used by azents."""

from types import TracebackType
from typing import Any

class _ExecMessage:
    """One message from an exec stream — stream ID and payload."""

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
    """aiodocker DockerContainer — only members used by the azents Runtime Provider."""

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
