"""aiodocker adapter for the Docker Provider."""

from collections.abc import Mapping, Sequence

import aiodocker
from aiodocker.containers import DockerContainer

from azents_runtime_provider_docker.docker_api import (
    DockerApi,
    DockerBindMount,
    DockerContainerInfo,
    DockerContainerSpec,
    DockerContainerState,
)


class AioDockerApi(DockerApi):
    """Docker API implementation backed by aiodocker."""

    def __init__(self, *, docker_host: str | None = None) -> None:
        """Initialize the adapter.

        :param docker_host: Optional Docker socket URL
        """
        self._docker_host = docker_host
        self._docker: aiodocker.Docker | None = None

    async def close(self) -> None:
        """Close the Docker client session."""
        if self._docker is not None:
            await self._docker.close()
            self._docker = None

    async def ensure_network(self, name: str) -> None:
        """Create the Docker network when missing."""
        docker = await self._get_docker()
        networks = await docker.networks.list(filters={"name": [name]})
        if not any(_mapping(network).get("Name") == name for network in networks):
            await docker.networks.create(
                {
                    "Name": name,
                    "Driver": "bridge",
                    "Labels": {"managed-by": "azents-runtime-provider-docker"},
                }
            )

    async def ensure_image(self, image: str) -> None:
        """Pull the Docker image when missing."""
        docker = await self._get_docker()
        try:
            await docker.images.inspect(image)
        except aiodocker.DockerError as exc:
            if exc.status != 404:
                raise
            await docker.images.pull(image)

    async def get_container(self, name: str) -> DockerContainerInfo | None:
        """Inspect one container by name."""
        docker = await self._get_docker()
        container = docker.containers.container(name)
        try:
            return _container_info(name, await container.show())
        except aiodocker.DockerError as exc:
            if exc.status == 404:
                return None
            raise

    async def create_container(self, spec: DockerContainerSpec) -> None:
        """Create a stopped Docker container."""
        docker = await self._get_docker()
        await docker.containers.create(
            config={
                "Image": spec.image,
                "User": spec.user,
                "WorkingDir": spec.working_dir,
                "Env": [f"{key}={value}" for key, value in spec.env.items()],
                "HostConfig": {
                    "SecurityOpt": ["seccomp=unconfined"],
                    "NetworkMode": spec.network,
                    "AutoRemove": False,
                    "Memory": spec.memory_bytes,
                    "CpuQuota": spec.cpu_quota,
                    "CpuPeriod": spec.cpu_period,
                    "Binds": [
                        f"{bind.host_path}:{bind.container_path}" for bind in spec.binds
                    ],
                    "ExtraHosts": list(spec.extra_hosts),
                },
                "Labels": dict(spec.labels),
            },
            name=spec.name,
        )

    async def start_container(self, name: str) -> None:
        """Start a container if Docker still knows it."""
        container = await self._container(name)
        await container.start()

    async def remove_container(self, name: str) -> None:
        """Remove a container if it exists."""
        try:
            container = await self._container(name)
            await container.delete(force=True)
        except aiodocker.DockerError as exc:
            if exc.status != 404:
                raise

    async def list_containers(
        self,
        labels: Mapping[str, str],
    ) -> Sequence[DockerContainerInfo]:
        """List containers matching labels."""
        docker = await self._get_docker()
        label_filters = [f"{key}={value}" for key, value in labels.items()]
        containers = await docker.containers.list(
            all=True,
            filters={"label": label_filters},
        )
        result: list[DockerContainerInfo] = []
        for container in containers:
            result.append(
                _container_info(
                    _container_name_from_object(container),
                    await container.show(),
                )
            )
        return tuple(result)

    async def _get_docker(self) -> aiodocker.Docker:
        if self._docker is None:
            self._docker = aiodocker.Docker(url=self._docker_host)
        return self._docker

    async def _container(self, name: str) -> DockerContainer:
        docker = await self._get_docker()
        return docker.containers.container(name)


def _container_info(name: str, raw_info: object) -> DockerContainerInfo:
    info = _mapping(raw_info)
    config = _mapping(info.get("Config"))
    state = _mapping(info.get("State"))
    labels = _string_mapping(config.get("Labels"))
    env = _env_mapping(config.get("Env"))
    mounts = _mounts(info.get("Mounts"))
    image = config.get("Image")
    user = config.get("User")
    status = state.get("Status")
    return DockerContainerInfo(
        name=name,
        image=image if isinstance(image, str) else "",
        user=user if isinstance(user, str) else None,
        labels=labels,
        env=env,
        binds=mounts,
        state=DockerContainerState(
            running=bool(state.get("Running")),
            restarting=bool(state.get("Restarting")),
            dead=bool(state.get("Dead")),
            status=status if isinstance(status, str) else None,
        ),
    )


def _container_name_from_object(container: DockerContainer) -> str:
    raw_id = getattr(container, "id", None)
    return raw_id if isinstance(raw_id, str) else ""


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, str):
            result[key] = item
    return result


def _env_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    result: dict[str, str] = {}
    for entry in value:
        if not isinstance(entry, str) or "=" not in entry:
            continue
        key, item = entry.split("=", 1)
        result[key] = item
    return result


def _mounts(value: object) -> tuple[DockerBindMount, ...]:
    if not isinstance(value, list):
        return ()
    mounts: list[DockerBindMount] = []
    for entry in value:
        item = _mapping(entry)
        source = item.get("Source")
        destination = item.get("Destination")
        if isinstance(source, str) and isinstance(destination, str):
            mounts.append(DockerBindMount(source, destination))
    return tuple(mounts)
