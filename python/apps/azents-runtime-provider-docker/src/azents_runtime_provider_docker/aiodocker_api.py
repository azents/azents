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
        host_config: dict[str, object] = {
            "SecurityOpt": list(spec.security_options),
            "CapAdd": list(spec.cap_add),
            "CapDrop": list(spec.cap_drop),
            "UsernsMode": spec.userns_mode,
            "Privileged": spec.privileged,
            "NetworkMode": spec.network,
            "AutoRemove": False,
            "Memory": spec.memory_bytes,
            "MemoryReservation": spec.memory_reservation_bytes,
            "CpuQuota": spec.cpu_quota,
            "CpuPeriod": spec.cpu_period,
            "CpuShares": spec.cpu_shares,
            "Binds": [
                (
                    f"{bind.host_path}:{bind.container_path}:ro"
                    if bind.read_only
                    else f"{bind.host_path}:{bind.container_path}"
                )
                for bind in spec.binds
            ],
            "ExtraHosts": list(spec.extra_hosts),
        }
        if spec.masked_paths is not None:
            host_config["MaskedPaths"] = list(spec.masked_paths)
        if spec.readonly_paths is not None:
            host_config["ReadonlyPaths"] = list(spec.readonly_paths)
        await docker.containers.create(
            config={
                "Image": spec.image,
                "User": spec.user,
                "WorkingDir": spec.working_dir,
                "Env": [f"{key}={value}" for key, value in spec.env.items()],
                "HostConfig": host_config,
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
    host_config = _mapping(info.get("HostConfig"))
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
        cap_add=_string_sequence(host_config.get("CapAdd")),
        cap_drop=_string_sequence(host_config.get("CapDrop")),
        security_options=_string_sequence(host_config.get("SecurityOpt")),
        userns_mode=_optional_string(host_config.get("UsernsMode")),
        masked_paths=_string_sequence(host_config.get("MaskedPaths")),
        readonly_paths=_string_sequence(host_config.get("ReadonlyPaths")),
        privileged=_required_bool(host_config.get("Privileged"), "Privileged"),
        state=DockerContainerState(
            running=_required_bool(state.get("Running"), "Running"),
            restarting=_required_bool(state.get("Restarting"), "Restarting"),
            dead=_required_bool(state.get("Dead"), "Dead"),
            status=_optional_string(status),
            exit_code=_optional_int(state.get("ExitCode"), "ExitCode"),
            oom_killed=_required_bool(state.get("OOMKilled"), "OOMKilled"),
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


def _string_sequence(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Docker string sequence is invalid.")
    return tuple(item for item in value if isinstance(item, str))


def _optional_string(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("Docker optional string is invalid.")
    return value


def _required_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"Docker {field} is invalid.")
    return value


def _optional_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Docker {field} is invalid.")
    return value


def _mounts(value: object) -> tuple[DockerBindMount, ...]:
    if not isinstance(value, list):
        return ()
    mounts: list[DockerBindMount] = []
    for entry in value:
        item = _mapping(entry)
        source = item.get("Source")
        destination = item.get("Destination")
        read_write = item.get("RW")
        if (
            isinstance(source, str)
            and isinstance(destination, str)
            and isinstance(read_write, bool)
        ):
            mounts.append(
                DockerBindMount(
                    host_path=source,
                    container_path=destination,
                    read_only=not read_write,
                )
            )
    return tuple(mounts)
