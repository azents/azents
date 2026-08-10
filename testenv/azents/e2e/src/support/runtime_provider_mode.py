"""Docker Runtime Provider fixture mode helpers."""

from collections.abc import Mapping

_DOCKER_PROCESS_CONTAINMENT_ENV = "AZENTS_E2E_DOCKER_PROCESS_CONTAINMENT"


def docker_process_containment_enabled(environ: Mapping[str, str]) -> bool:
    """Return whether the E2E lane explicitly enables Docker containment."""
    value = environ.get(_DOCKER_PROCESS_CONTAINMENT_ENV)
    if value is None:
        return False
    normalized = value.lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise RuntimeError(f"{_DOCKER_PROCESS_CONTAINMENT_ENV} must be true or false")


def docker_provider_containment_environment(*, enabled: bool) -> dict[str, str]:
    """Return trusted Provider deployment settings for the selected fixture mode."""
    if not enabled:
        return {}
    return {
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_BACKEND": "bwrap",
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_SECURITY_PROFILE": (
            "azents-runtime-bwrap"
        ),
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_QUALIFICATION_TIMEOUT_SECONDS": "20",
    }


def docker_infrastructure_profile_spec(
    *,
    network_name: str,
    containment_enabled: bool,
) -> dict[str, object]:
    """Return the exact direct or contained Docker Infrastructure Profile spec."""
    spec: dict[str, object] = {
        "profile_kind": "docker_container",
        "contract_family": "docker.container-profile",
        "schema_version": 2 if containment_enabled else 1,
        "runner_resources": {
            "cpu_reservation_millicores": None,
            "cpu_limit_millicores": None,
            "memory_reservation_bytes": None,
            "memory_limit_bytes": None,
        },
        "network_name": network_name,
    }
    if containment_enabled:
        spec["process_containment"] = {"schema_version": 1}
    return spec
