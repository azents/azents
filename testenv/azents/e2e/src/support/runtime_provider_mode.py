"""Docker Runtime Provider fixture helpers."""


def docker_infrastructure_profile_spec(*, network_name: str) -> dict[str, object]:
    """Return the direct Docker Infrastructure Profile used by E2E fixtures."""
    return {
        "profile_kind": "docker_container",
        "contract_family": "docker.container-profile",
        "schema_version": 1,
        "runner_resources": {
            "cpu_reservation_millicores": None,
            "cpu_limit_millicores": None,
            "memory_reservation_bytes": None,
            "memory_limit_bytes": None,
        },
        "network_name": network_name,
    }
