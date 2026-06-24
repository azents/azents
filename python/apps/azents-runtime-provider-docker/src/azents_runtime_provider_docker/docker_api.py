"""Docker API boundary for the Docker Provider."""

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Protocol


@dataclasses.dataclass(frozen=True)
class DockerBindMount:
    """Host directory bind mounted into a Runtime container."""

    host_path: str
    container_path: str


@dataclasses.dataclass(frozen=True)
class DockerContainerState:
    """Subset of Docker container state used by the Provider."""

    running: bool
    restarting: bool
    dead: bool
    status: str | None


@dataclasses.dataclass(frozen=True)
class DockerContainerInfo:
    """Docker container inspection data used by the Provider."""

    name: str
    image: str
    user: str | None
    labels: Mapping[str, str]
    env: Mapping[str, str]
    binds: Sequence[DockerBindMount]
    state: DockerContainerState


@dataclasses.dataclass(frozen=True)
class DockerContainerSpec:
    """Container create request emitted by the Provider."""

    name: str
    image: str
    user: str | None
    working_dir: str
    env: Mapping[str, str]
    labels: Mapping[str, str]
    binds: Sequence[DockerBindMount]
    network: str
    memory_bytes: int
    cpu_quota: int
    cpu_period: int
    extra_hosts: Sequence[str]


class DockerApi(Protocol):
    """Docker operations required by the Provider lifecycle."""

    async def ensure_network(self, name: str) -> None:
        """Create the Docker network when missing."""
        ...

    async def ensure_image(self, image: str) -> None:
        """Pull or otherwise make sure the image is available."""
        ...

    async def get_container(self, name: str) -> DockerContainerInfo | None:
        """Return container info by name."""
        ...

    async def create_container(self, spec: DockerContainerSpec) -> None:
        """Create a stopped container."""
        ...

    async def start_container(self, name: str) -> None:
        """Start a created container."""
        ...

    async def remove_container(self, name: str) -> None:
        """Remove a container if it exists."""
        ...

    async def list_containers(
        self, labels: Mapping[str, str]
    ) -> Sequence[DockerContainerInfo]:
        """List containers matching all labels."""
        ...
