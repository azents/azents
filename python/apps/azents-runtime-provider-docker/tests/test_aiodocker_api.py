"""Docker API adapter decoding tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from azents_runtime_provider_docker.aiodocker_api import AioDockerApi, _container_info
from azents_runtime_provider_docker.docker_api import (
    DockerBindMount,
    DockerContainerSpec,
)


@pytest.mark.parametrize("name", ["azents-runtime-first", "azents-runtime-second"])
async def test_create_preserves_runtime_hostname_across_container_replacement(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Native persistent profiles must see the same machine after replacement."""
    create = AsyncMock()
    docker = MagicMock()
    docker.containers.create = create
    adapter = AioDockerApi()
    monkeypatch.setattr(adapter, "_get_docker", AsyncMock(return_value=docker))
    spec = DockerContainerSpec(
        name=name,
        image="runner:synthetic",
        user="1000:1000",
        working_dir="/runtime/home",
        env={},
        labels={},
        binds=(),
        network="runtime-network",
        memory_bytes=None,
        memory_reservation_bytes=None,
        cpu_quota=None,
        cpu_period=100000,
        cpu_shares=None,
        extra_hosts=(),
        cap_add=(),
        cap_drop=("ALL",),
        security_options=("no-new-privileges",),
        userns_mode=None,
        masked_paths=None,
        readonly_paths=None,
        privileged=False,
    )
    await adapter.create_container(spec)
    await adapter.create_container(spec)
    assert create.await_count == 2
    for call in create.await_args_list:
        assert call.kwargs["name"] == name
        assert call.kwargs["config"]["Hostname"] == name


def test_container_info_decodes_security_mount_and_terminal_evidence() -> None:
    info = _container_info(
        "runtime-1",
        {
            "Config": {
                "Image": "runner:latest",
                "User": "1000:1000",
                "Labels": {"label": "value"},
                "Env": ["HOME=/runtime/home"],
            },
            "HostConfig": {
                "CapAdd": [],
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges"],
                "UsernsMode": "",
                "MaskedPaths": ["/proc/kcore"],
                "ReadonlyPaths": ["/proc/asound"],
                "Privileged": False,
            },
            "State": {
                "Running": False,
                "Restarting": False,
                "Dead": False,
                "Status": "exited",
                "ExitCode": 23,
                "OOMKilled": False,
            },
            "Mounts": [
                {
                    "Source": "/host/workspace",
                    "Destination": "/runtime/home",
                    "RW": False,
                }
            ],
        },
    )

    assert info.user == "1000:1000"
    assert info.cap_add == ()
    assert info.cap_drop == ("ALL",)
    assert info.security_options == ("no-new-privileges",)
    assert info.userns_mode is None
    assert info.masked_paths == ("/proc/kcore",)
    assert info.readonly_paths == ("/proc/asound",)
    assert info.privileged is False
    assert info.binds == (
        DockerBindMount(
            host_path="/host/workspace",
            container_path="/runtime/home",
            read_only=True,
        ),
    )
    assert info.state.status == "exited"
    assert info.state.exit_code == 23
    assert info.state.oom_killed is False


def test_container_info_rejects_untyped_security_evidence() -> None:
    with pytest.raises(ValueError, match="Privileged"):
        _container_info(
            "runtime-1",
            {
                "Config": {
                    "Image": "runner:latest",
                    "User": "1000:1000",
                    "Labels": {},
                    "Env": [],
                },
                "HostConfig": {
                    "CapAdd": [],
                    "CapDrop": [],
                    "SecurityOpt": [],
                    "UsernsMode": "",
                    "MaskedPaths": [],
                    "ReadonlyPaths": [],
                    "Privileged": "false",
                },
                "State": {
                    "Running": False,
                    "Restarting": False,
                    "Dead": False,
                    "Status": "created",
                    "ExitCode": None,
                    "OOMKilled": False,
                },
                "Mounts": [],
            },
        )
