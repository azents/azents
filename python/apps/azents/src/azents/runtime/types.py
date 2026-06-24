"""Agent Runtime shared execution types."""

import dataclasses
from typing import Literal, Protocol

ExecSignal = Literal["TERM", "KILL"]


@dataclasses.dataclass(frozen=True)
class ExecResult:
    """Command execution result."""

    stdout: str
    stderr: str
    exit_code: int


@dataclasses.dataclass(frozen=True)
class RuntimeDomainConfig:
    """Network domain filter config for runtime operations."""

    allowed_domains: tuple[str, ...]
    denied_domains: tuple[str, ...]
    provider_id: str | None = None


class RuntimeNotFoundError(RuntimeError):
    """Runtime backend was not found."""


class RuntimeExecClient(Protocol):
    """Cancelable execution target."""

    async def exec(
        self,
        command: str,
        *,
        timeout: int = 30,
        env: dict[str, str] | None = None,
        exec_id: str | None = None,
    ) -> ExecResult:
        """Execute a command."""
        ...

    async def terminate_exec(
        self,
        exec_id: str,
        *,
        signal: ExecSignal = "TERM",
    ) -> None:
        """Terminate a running command."""
        ...

    async def write_file(self, path: str, content: bytes) -> None:
        """Write a file."""
        ...

    async def read_file(self, path: str) -> bytes:
        """Read a file."""
        ...

    async def close(self) -> None:
        """Release backend resources."""
        ...
