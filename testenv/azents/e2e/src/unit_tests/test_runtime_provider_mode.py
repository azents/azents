"""Unit tests for Docker Runtime Provider fixtures."""

from support.runtime_provider_mode import docker_infrastructure_profile_spec


def test_docker_profile_uses_direct_schema_v1() -> None:
    assert docker_infrastructure_profile_spec(
        network_name="runtime-network",
    ) == {
        "profile_kind": "docker_container",
        "contract_family": "docker.container-profile",
        "schema_version": 1,
        "runner_resources": {
            "cpu_reservation_millicores": None,
            "cpu_limit_millicores": None,
            "memory_reservation_bytes": None,
            "memory_limit_bytes": None,
        },
        "network_name": "runtime-network",
    }
