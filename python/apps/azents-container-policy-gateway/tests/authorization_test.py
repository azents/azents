"""Closed Docker API authorization tests."""

import dataclasses
import json

import pytest
from azents_runtime_control.execution_policy import RuntimeExecutionPolicy
from conftest import build_context, json_headers, policy

from azents_container_policy_gateway.authorization import (
    authorize_request,
    request_body_limit,
)
from azents_container_policy_gateway.models import GatewayAuthorizationDenied


def _authorize(
    runtime_policy: RuntimeExecutionPolicy,
    *,
    method: str,
    path: str,
    query: tuple[tuple[str, str], ...] = (),
    headers: dict[str, str] | None = None,
    body: object | bytes | None = None,
) -> bytes:
    if body is None:
        encoded = b""
    elif isinstance(body, bytes):
        encoded = body
    else:
        encoded = json.dumps(body).encode()
    request = authorize_request(
        policy=runtime_policy,
        runtime_id="runtime-1",
        method=method,
        raw_path=path,
        query=query,
        headers=headers or {},
        body=encoded,
    )
    return request.body


def _docker_cli_create_wire_body() -> dict[str, object]:
    """Return pinned Docker CLI 28.5.2 create defaults."""
    return {
        "Hostname": "",
        "Domainname": "",
        "User": "",
        "AttachStdin": False,
        "AttachStdout": True,
        "AttachStderr": True,
        "Tty": False,
        "OpenStdin": False,
        "StdinOnce": False,
        "Env": [],
        "Cmd": ["echo", "ok"],
        "Image": "busybox",
        "Volumes": {},
        "WorkingDir": "",
        "Entrypoint": None,
        "NetworkDisabled": False,
        "MacAddress": "",
        "OnBuild": None,
        "Labels": {},
        "HostConfig": {
            "Binds": None,
            "ContainerIDFile": "",
            "LogConfig": {"Type": "", "Config": {}},
            "NetworkMode": "default",
            "PortBindings": {},
            "RestartPolicy": {"Name": "", "MaximumRetryCount": 0},
            "AutoRemove": False,
            "VolumeDriver": "",
            "VolumesFrom": None,
            "ConsoleSize": [0, 0],
            "CapAdd": None,
            "CapDrop": None,
            "CgroupnsMode": "",
            "Dns": [],
            "DnsOptions": [],
            "DnsSearch": [],
            "ExtraHosts": None,
            "GroupAdd": None,
            "IpcMode": "",
            "Cgroup": "",
            "Links": None,
            "OomScoreAdj": 0,
            "PidMode": "",
            "Privileged": False,
            "PublishAllPorts": False,
            "ReadonlyRootfs": False,
            "SecurityOpt": None,
            "Tmpfs": {},
            "UTSMode": "",
            "UsernsMode": "",
            "ShmSize": 67_108_864,
            "Sysctls": {},
            "Runtime": "",
            "Isolation": "",
            "CpuShares": 0,
            "Memory": 0,
            "NanoCpus": 0,
            "CgroupParent": "",
            "BlkioWeight": 0,
            "BlkioWeightDevice": None,
            "BlkioDeviceReadBps": None,
            "BlkioDeviceWriteBps": None,
            "BlkioDeviceReadIOps": None,
            "BlkioDeviceWriteIOps": None,
            "CpuPeriod": 0,
            "CpuQuota": 0,
            "CpuRealtimePeriod": 0,
            "CpuRealtimeRuntime": 0,
            "CpusetCpus": "",
            "CpusetMems": "",
            "Devices": None,
            "DeviceCgroupRules": None,
            "DeviceRequests": None,
            "MemoryReservation": 0,
            "MemorySwap": 0,
            "MemorySwappiness": -1,
            "OomKillDisable": None,
            "PidsLimit": 0,
            "Ulimits": None,
            "CpuCount": 0,
            "CpuPercent": 0,
            "IOMaximumIOps": 0,
            "IOMaximumBandwidth": 0,
            "Mounts": [],
            "MaskedPaths": None,
            "ReadonlyPaths": None,
        },
        "NetworkingConfig": {"EndpointsConfig": {}},
    }


def _compose_network_create_wire_body() -> dict[str, object]:
    """Return pinned Compose 2.40.3 network-create defaults."""
    return {
        "Name": "demo_default",
        "Driver": "",
        "Scope": "",
        "EnableIPv4": None,
        "EnableIPv6": None,
        "IPAM": None,
        "Internal": False,
        "Attachable": False,
        "Ingress": False,
        "ConfigOnly": False,
        "ConfigFrom": None,
        "Options": None,
        "Labels": {"com.docker.compose.project": "demo"},
    }


@pytest.mark.parametrize(
    ("runtime_policy", "method", "path"),
    [
        (policy(), "POST", "/v1.51/build"),
        (policy(image_build=True), "POST", "/v1.51/containers/create"),
        (policy(container_run=True), "POST", "/v1.51/networks/create"),
    ],
)
def test_modules_are_independently_authorized(
    runtime_policy: RuntimeExecutionPolicy,
    method: str,
    path: str,
) -> None:
    with pytest.raises(GatewayAuthorizationDenied, match="module"):
        _authorize(
            runtime_policy,
            method=method,
            path=path,
            headers=json_headers(),
            body={},
        )


@pytest.mark.parametrize(
    "field",
    [
        "Binds",
        "CapAdd",
        "Devices",
        "DeviceRequests",
        "PidMode",
        "IpcMode",
        "UTSMode",
        "CgroupnsMode",
        "UsernsMode",
        "Runtime",
        "SecurityOpt",
        "Sysctls",
        "Dns",
        "DnsOptions",
        "DnsSearch",
        "ExtraHosts",
        "PortBindings",
        "VolumesFrom",
        "Tmpfs",
        "CgroupParent",
        "DeviceCgroupRules",
        "Ulimits",
        "Links",
        "GroupAdd",
        "StorageOpt",
        "VolumeDriver",
    ],
)
def test_container_create_rejects_unsafe_host_fields(
    run_policy: RuntimeExecutionPolicy,
    field: str,
) -> None:
    with pytest.raises(GatewayAuthorizationDenied, match=field):
        _authorize(
            run_policy,
            method="POST",
            path="/v1.51/containers/create",
            headers=json_headers(),
            body={"Image": "busybox", "HostConfig": {field: ["unsafe"]}},
        )


@pytest.mark.parametrize(
    "host_config",
    [
        {"Privileged": True},
        {"PublishAllPorts": True},
        {"NetworkMode": "host"},
        {"NetworkMode": "container:other"},
        {"Mounts": [{"Type": "bind", "Source": "/host", "Target": "/data"}]},
        {"Memory": 2_147_483_649},
        {"Memory": False},
        {"NanoCpus": 1_000_000_001},
        {"NanoCpus": False},
        {"PidsLimit": 257},
        {"PidsLimit": False},
        {"PidsLimit": []},
    ],
)
def test_container_create_rejects_privilege_and_resource_escape(
    run_policy: RuntimeExecutionPolicy,
    host_config: dict[str, object],
) -> None:
    with pytest.raises(GatewayAuthorizationDenied):
        _authorize(
            run_policy,
            method="POST",
            path="/v1.51/containers/create",
            headers=json_headers(),
            body={"Image": "busybox", "HostConfig": host_config},
        )


def test_container_create_accepts_named_volume_and_injects_runtime_labels(
    compose_policy: RuntimeExecutionPolicy,
) -> None:
    body = _authorize(
        compose_policy,
        method="POST",
        path="/v1.51/containers/create",
        headers=json_headers(),
        body={
            "Image": "busybox",
            "Labels": {"com.docker.compose.project": "demo"},
            "HostConfig": {
                "Memory": 1_073_741_824,
                "NanoCpus": 500_000_000,
                "PidsLimit": 128,
                "NetworkMode": "demo_default",
                "Mounts": [
                    {
                        "Type": "volume",
                        "Source": "demo_data",
                        "Target": "/data",
                    }
                ],
            },
            "NetworkingConfig": {
                "EndpointsConfig": {
                    "demo_default": {"Aliases": ["app"]},
                }
            },
        },
    )

    value = json.loads(body)
    assert value["Labels"]["azents/runtime-id"] == "runtime-1"
    assert value["HostConfig"]["Mounts"][0]["Type"] == "volume"


def test_pinned_docker_cli_create_defaults_are_normalized(
    run_policy: RuntimeExecutionPolicy,
) -> None:
    request = authorize_request(
        policy=run_policy,
        runtime_id="runtime-1",
        method="POST",
        raw_path="/v1.51/containers/create",
        query=(),
        headers=json_headers(),
        body=json.dumps(_docker_cli_create_wire_body()).encode(),
    )

    value = json.loads(request.body)
    assert request.requested_pids_limit == 32
    assert value["HostConfig"]["PidsLimit"] == 32
    assert value["HostConfig"]["ShmSize"] == 67_108_864
    assert "MemorySwappiness" not in value["HostConfig"]
    assert value["AttachStdout"] is True
    assert value["AttachStderr"] is True
    for dropped in (
        "Hostname",
        "Domainname",
        "AttachStdin",
        "Volumes",
        "NetworkDisabled",
        "MacAddress",
        "OnBuild",
    ):
        assert dropped not in value


@pytest.mark.parametrize("memory_swappiness", [1, 50, 100])
def test_container_create_rejects_explicit_memory_swappiness(
    run_policy: RuntimeExecutionPolicy,
    memory_swappiness: int,
) -> None:
    body = _docker_cli_create_wire_body()
    host_config = body["HostConfig"]
    assert isinstance(host_config, dict)
    host_config["MemorySwappiness"] = memory_swappiness

    with pytest.raises(GatewayAuthorizationDenied, match="MemorySwappiness"):
        _authorize(
            run_policy,
            method="POST",
            path="/v1.51/containers/create",
            headers=json_headers(),
            body=body,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Hostname", "custom-host"),
        ("Domainname", "example.test"),
        ("AttachStdin", True),
        ("NetworkDisabled", True),
        ("MacAddress", "02:42:ac:11:00:02"),
        ("Volumes", {"/data": {}}),
    ],
)
def test_container_create_denies_non_default_wire_authority(
    run_policy: RuntimeExecutionPolicy,
    field: str,
    value: object,
) -> None:
    body = _docker_cli_create_wire_body()
    body[field] = value

    with pytest.raises(GatewayAuthorizationDenied):
        _authorize(
            run_policy,
            method="POST",
            path="/v1.51/containers/create",
            headers=json_headers(),
            body=body,
        )


@pytest.mark.parametrize("pids_limit", [None, 0, -1])
def test_unbounded_pids_values_are_replaced_with_policy_bound(
    run_policy: RuntimeExecutionPolicy,
    pids_limit: int | None,
) -> None:
    body = _docker_cli_create_wire_body()
    host_config = body["HostConfig"]
    assert isinstance(host_config, dict)
    host_config["PidsLimit"] = pids_limit

    request = authorize_request(
        policy=run_policy,
        runtime_id="runtime-1",
        method="POST",
        raw_path="/v1.51/containers/create",
        query=(),
        headers=json_headers(),
        body=json.dumps(body).encode(),
    )

    assert request.requested_pids_limit == 32
    assert json.loads(request.body)["HostConfig"]["PidsLimit"] == 32


@pytest.mark.parametrize("pids_limit", [None, 0, -1])
def test_null_pid_ceiling_preserves_unlimited_engine_semantics(
    pids_limit: int | None,
) -> None:
    runtime_policy = policy(
        container_run=True,
        bounded_nested_containers=False,
    )
    runtime_policy = dataclasses.replace(
        runtime_policy,
        resources=dataclasses.replace(
            runtime_policy.resources,
            cpu_limit_millicores=None,
            memory_limit_bytes=None,
        ),
    )
    body = _docker_cli_create_wire_body()
    host_config = body["HostConfig"]
    assert isinstance(host_config, dict)
    host_config["PidsLimit"] = pids_limit

    request = authorize_request(
        policy=runtime_policy,
        runtime_id="runtime-1",
        method="POST",
        raw_path="/v1.51/containers/create",
        query=(),
        headers=json_headers(),
        body=json.dumps(body).encode(),
    )

    assert request.requested_pids_limit is None
    assert "PidsLimit" not in json.loads(request.body)["HostConfig"]


def test_null_resource_ceilings_allow_explicit_container_resources() -> None:
    runtime_policy = policy(
        container_run=True,
        bounded_nested_containers=False,
    )
    runtime_policy = dataclasses.replace(
        runtime_policy,
        resources=dataclasses.replace(
            runtime_policy.resources,
            cpu_limit_millicores=None,
            memory_limit_bytes=None,
        ),
    )
    body = _authorize(
        runtime_policy,
        method="POST",
        path="/v1.51/containers/create",
        headers=json_headers(),
        body={
            "Image": "busybox",
            "HostConfig": {
                "NanoCpus": 4_000_000_000,
                "Memory": 8_589_934_592,
                "PidsLimit": 1_024,
            },
        },
    )

    host_config = json.loads(body)["HostConfig"]
    assert host_config["NanoCpus"] == 4_000_000_000
    assert host_config["Memory"] == 8_589_934_592
    assert host_config["PidsLimit"] == 1_024


def test_pinned_compose_network_defaults_are_normalized(
    compose_policy: RuntimeExecutionPolicy,
) -> None:
    body = _authorize(
        compose_policy,
        method="POST",
        path="/v1.51/networks/create",
        headers=json_headers(),
        body=_compose_network_create_wire_body(),
    )

    value = json.loads(body)
    assert value == {
        "Name": "demo_default",
        "Driver": "bridge",
        "Internal": False,
        "Attachable": False,
        "Labels": {
            "com.docker.compose.project": "demo",
            "azents/runtime-id": "runtime-1",
        },
    }


def test_pinned_compose_endpoint_defaults_are_normalized(
    compose_policy: RuntimeExecutionPolicy,
) -> None:
    body = _authorize(
        compose_policy,
        method="POST",
        path="/v1.51/containers/create",
        headers=json_headers(),
        body={
            "Image": "busybox",
            "HostConfig": {"NetworkMode": "demo_default"},
            "NetworkingConfig": {
                "EndpointsConfig": {
                    "demo_default": {
                        "IPAMConfig": None,
                        "Links": None,
                        "Aliases": ["app"],
                        "MacAddress": "",
                        "DriverOpts": None,
                        "GwPriority": 0,
                        "NetworkID": "",
                        "EndpointID": "",
                        "Gateway": "",
                        "IPAddress": "",
                        "IPPrefixLen": 0,
                        "IPv6Gateway": "",
                        "GlobalIPv6Address": "",
                        "GlobalIPv6PrefixLen": 0,
                        "DNSNames": ["app"],
                    }
                }
            },
        },
    )

    endpoint = json.loads(body)["NetworkingConfig"]["EndpointsConfig"]["demo_default"]
    assert endpoint == {"Aliases": ["app"], "DNSNames": ["app"]}


@pytest.mark.parametrize(
    "network_field",
    [
        {"EnableIPv4": False},
        {"EnableIPv6": True},
        {"IPAM": {"Driver": "default"}},
        {"Options": {"com.docker.network.bridge.name": "host-bridge"}},
    ],
)
def test_network_create_denies_non_default_wire_authority(
    compose_policy: RuntimeExecutionPolicy,
    network_field: dict[str, object],
) -> None:
    body = _compose_network_create_wire_body()
    body.update(network_field)

    with pytest.raises(GatewayAuthorizationDenied):
        _authorize(
            compose_policy,
            method="POST",
            path="/v1.51/networks/create",
            headers=json_headers(),
            body=body,
        )


def test_build_rejects_opaque_session_and_registry_secrets(
    build_policy: RuntimeExecutionPolicy,
) -> None:
    with pytest.raises(GatewayAuthorizationDenied, match="classic build"):
        _authorize(
            build_policy,
            method="POST",
            path="/v1.51/build",
            query=(("version", "2"),),
            body=b"tar",
        )

    with pytest.raises(GatewayAuthorizationDenied, match="headers"):
        _authorize(
            build_policy,
            method="POST",
            path="/v1.51/build",
            headers={"X-Registry-Config": "secret"},
            body=b"tar",
        )


def test_unknown_api_version_endpoint_query_and_body_are_denied(
    run_policy: RuntimeExecutionPolicy,
) -> None:
    with pytest.raises(GatewayAuthorizationDenied):
        _authorize(run_policy, method="GET", path="/v1.50/containers/json")
    with pytest.raises(GatewayAuthorizationDenied):
        _authorize(run_policy, method="POST", path="/v1.51/containers/abc/exec")
    with pytest.raises(GatewayAuthorizationDenied):
        _authorize(
            run_policy,
            method="GET",
            path="/v1.51/containers/json",
            query=(("unsafe", "1"),),
        )
    with pytest.raises(GatewayAuthorizationDenied):
        _authorize(
            run_policy,
            method="GET",
            path="/v1.51/containers/json",
            body=b"unexpected",
        )


def test_compose_network_and_volume_drivers_are_fixed(
    compose_policy: RuntimeExecutionPolicy,
) -> None:
    with pytest.raises(GatewayAuthorizationDenied, match="bridge"):
        _authorize(
            compose_policy,
            method="POST",
            path="/v1.51/networks/create",
            headers=json_headers(),
            body={"Name": "demo", "Driver": "macvlan"},
        )
    with pytest.raises(GatewayAuthorizationDenied, match="local"):
        _authorize(
            compose_policy,
            method="POST",
            path="/v1.51/volumes/create",
            headers=json_headers(),
            body={"Name": "demo", "Driver": "nfs"},
        )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1.51/images/json"),
        ("GET", "/v1.51/images/busybox/json"),
        ("POST", "/v1.51/images/create"),
        ("DELETE", "/v1.51/images/busybox"),
        ("POST", "/v1.51/build"),
        ("GET", "/v1.51/containers/json"),
        ("POST", "/v1.51/containers/create"),
        ("GET", "/v1.51/containers/demo/json"),
        ("GET", "/v1.51/containers/demo/logs"),
        ("POST", "/v1.51/containers/demo/start"),
        ("POST", "/v1.51/containers/demo/stop"),
        ("POST", "/v1.51/containers/demo/kill"),
        ("POST", "/v1.51/containers/demo/wait"),
        ("DELETE", "/v1.51/containers/demo"),
        ("GET", "/v1.51/events"),
        ("GET", "/v1.51/networks"),
        ("GET", "/v1.51/networks/demo"),
        ("POST", "/v1.51/networks/create"),
        ("POST", "/v1.51/networks/demo/connect"),
        ("POST", "/v1.51/networks/demo/disconnect"),
        ("DELETE", "/v1.51/networks/demo"),
        ("GET", "/v1.51/volumes"),
        ("GET", "/v1.51/volumes/demo"),
        ("POST", "/v1.51/volumes/create"),
        ("DELETE", "/v1.51/volumes/demo"),
    ],
)
def test_every_authority_bearing_route_is_disabled_by_default(
    method: str,
    path: str,
) -> None:
    with pytest.raises(GatewayAuthorizationDenied, match="module"):
        _authorize(policy(), method=method, path=path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PATCH", "/v1.51/containers/demo"),
        ("POST", "/v1.51/containers/demo/logs"),
        ("GET", "/v1.51/build"),
        ("POST", "/v1.51/images/busybox/json"),
        ("POST", "/v1.51/session"),
    ],
)
def test_unsupported_methods_and_paths_are_denied(
    run_policy: RuntimeExecutionPolicy,
    method: str,
    path: str,
) -> None:
    with pytest.raises(GatewayAuthorizationDenied):
        _authorize(run_policy, method=method, path=path)


def test_query_and_header_surface_is_default_deny(
    run_policy: RuntimeExecutionPolicy,
) -> None:
    with pytest.raises(GatewayAuthorizationDenied, match="Duplicate"):
        _authorize(
            run_policy,
            method="GET",
            path="/v1.51/containers/json",
            query=(("all", "1"), ("all", "0")),
        )
    with pytest.raises(GatewayAuthorizationDenied, match="boolean"):
        _authorize(
            run_policy,
            method="GET",
            path="/v1.51/containers/json",
            query=(("all", "yes"),),
        )
    with pytest.raises(GatewayAuthorizationDenied, match="headers"):
        _authorize(
            run_policy,
            method="GET",
            path="/v1.51/containers/json",
            headers={"X-Unrecognized": "value"},
        )


def test_build_requires_local_bounded_tar_and_denies_entitlements(
    build_policy: RuntimeExecutionPolicy,
) -> None:
    context = build_context()
    request = authorize_request(
        policy=build_policy,
        runtime_id="runtime-1",
        method="POST",
        raw_path="/v1.51/build",
        query=(("version", "1"), ("networkmode", "none")),
        headers={"Content-Type": "application/x-tar"},
        body=context,
    )
    assert request.operation == "images.build"
    assert request.body == context

    with pytest.raises(GatewayAuthorizationDenied, match="tar"):
        _authorize(
            build_policy,
            method="POST",
            path="/v1.51/build",
            headers={"Content-Type": "application/x-tar"},
            body=b"not-a-tar",
        )
    with pytest.raises(GatewayAuthorizationDenied, match="query"):
        _authorize(
            build_policy,
            method="POST",
            path="/v1.51/build",
            query=(("allow", "security.insecure"),),
            headers={"Content-Type": "application/x-tar"},
            body=context,
        )
    with pytest.raises(GatewayAuthorizationDenied, match="build-context path"):
        _authorize(
            build_policy,
            method="POST",
            path="/v1.51/build",
            query=(("dockerfile", "../Dockerfile"),),
            headers={"Content-Type": "application/x-tar"},
            body=context,
        )


def test_request_body_limits_distinguish_build_from_other_routes(
    build_policy: RuntimeExecutionPolicy,
) -> None:
    assert (
        request_body_limit(
            build_policy,
            method="POST",
            raw_path="/v1.51/build",
        )
        == 64 * 1024 * 1024
    )
    assert (
        request_body_limit(
            build_policy,
            method="POST",
            raw_path="/v1.51/containers/create",
        )
        == 2 * 1024 * 1024
    )


@pytest.mark.parametrize(
    "body",
    [
        {"Image": "busybox", "Volumes": {"/data": {}}},
        {
            "Image": "busybox",
            "NetworkingConfig": {
                "EndpointsConfig": {"demo": {"IPAddress": "172.18.0.10"}}
            },
        },
        {
            "Image": "busybox",
            "HostConfig": {
                "LogConfig": {"Type": "syslog", "Config": {}},
            },
        },
        {
            "Image": "busybox",
            "HostConfig": {
                "RestartPolicy": {"Name": "always"},
            },
        },
        {
            "Image": "busybox",
            "HostConfig": {
                "Mounts": [
                    {
                        "Type": "volume",
                        "Source": "demo",
                        "Target": "/data",
                        "VolumeOptions": {
                            "DriverConfig": {"Name": "local", "Options": {}}
                        },
                    }
                ]
            },
        },
    ],
)
def test_container_create_denies_additional_storage_network_and_driver_escape(
    compose_policy: RuntimeExecutionPolicy,
    body: dict[str, object],
) -> None:
    with pytest.raises(GatewayAuthorizationDenied):
        _authorize(
            compose_policy,
            method="POST",
            path="/v1.51/containers/create",
            headers=json_headers(),
            body=body,
        )


def test_container_create_records_named_resource_ownership_requirements(
    compose_policy: RuntimeExecutionPolicy,
) -> None:
    request = authorize_request(
        policy=compose_policy,
        runtime_id="runtime-1",
        method="POST",
        raw_path="/v1.51/containers/create",
        query=(),
        headers=json_headers(),
        body=json.dumps(
            {
                "Image": "busybox",
                "HostConfig": {
                    "NetworkMode": "demo_default",
                    "Mounts": [
                        {
                            "Type": "volume",
                            "Source": "demo_data",
                            "Target": "/data",
                        }
                    ],
                },
                "NetworkingConfig": {
                    "EndpointsConfig": {"demo_default": {"Aliases": ["app"]}}
                },
            }
        ).encode(),
    )

    assert request.required_volumes == ("demo_data",)
    assert request.required_networks == ("demo_default",)


def test_network_membership_records_container_ownership_requirement(
    compose_policy: RuntimeExecutionPolicy,
) -> None:
    request = authorize_request(
        policy=compose_policy,
        runtime_id="runtime-1",
        method="POST",
        raw_path="/v1.51/networks/demo/connect",
        query=(),
        headers=json_headers(),
        body=json.dumps({"Container": "demo-container"}).encode(),
    )

    assert request.required_containers == ("demo-container",)
