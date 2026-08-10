"""Unit tests for Docker Runtime Provider fixture modes."""

import pytest

from support.runtime_provider_mode import (
    docker_infrastructure_profile_spec,
    docker_process_containment_enabled,
    docker_provider_containment_environment,
)


@pytest.mark.parametrize(
    ("environ", "expected"),
    (
        ({}, False),
        ({"AZENTS_E2E_DOCKER_PROCESS_CONTAINMENT": "false"}, False),
        ({"AZENTS_E2E_DOCKER_PROCESS_CONTAINMENT": "TRUE"}, True),
    ),
)
def test_containment_mode_is_explicit(
    environ: dict[str, str],
    expected: bool,
) -> None:
    assert docker_process_containment_enabled(environ) is expected


def test_containment_mode_rejects_ambiguous_values() -> None:
    with pytest.raises(RuntimeError, match="must be true or false"):
        docker_process_containment_enabled(
            {"AZENTS_E2E_DOCKER_PROCESS_CONTAINMENT": "enabled"}
        )


def test_direct_mode_omits_containment_settings_and_uses_schema_v1() -> None:
    assert docker_provider_containment_environment(enabled=False) == {}
    assert docker_infrastructure_profile_spec(
        network_name="runtime-network",
        containment_enabled=False,
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


def test_contained_mode_configures_apparmor_backed_schema_v2() -> None:
    assert docker_provider_containment_environment(enabled=True) == {
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_BACKEND": "bwrap",
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_SECURITY_PROFILE": (
            "azents-runtime-bwrap"
        ),
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_QUALIFICATION_TIMEOUT_SECONDS": "20",
    }
    assert docker_infrastructure_profile_spec(
        network_name="runtime-network",
        containment_enabled=True,
    ) == {
        "profile_kind": "docker_container",
        "contract_family": "docker.container-profile",
        "schema_version": 2,
        "runner_resources": {
            "cpu_reservation_millicores": None,
            "cpu_limit_millicores": None,
            "memory_reservation_bytes": None,
            "memory_limit_bytes": None,
        },
        "network_name": "runtime-network",
        "process_containment": {"schema_version": 1},
    }
