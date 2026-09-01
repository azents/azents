"""Exercise persistent Nix lifecycle through the production Kubernetes Provider."""

import asyncio
import json
import os
import sys

from azents_runtime_control.provider import (
    JsonValue,
    RuntimeContainerAuth,
    RuntimeDesiredState,
    RuntimeIdentity,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
)
from azents_runtime_control.runtime_configuration import (
    RuntimeConfigurationEnvelope,
    RuntimeConfigurationEvidence,
    canonical_runtime_configuration_json,
)

from azents_runtime_provider_kubernetes.kubernetes_http import KubernetesHttpApi
from azents_runtime_provider_kubernetes.main import (
    ProviderSettings,
    prepare_runtime_provider,
)

_RUNTIME_ID = "nix-phase3"
_WORKSPACE_PATH = "/workspace/agent"
_STORAGE_CLASS_NAME = "standard"
_ACTIONS = {
    "start": (RuntimeLifecycleCommandType.START, 1, "direct"),
    "recreate": (RuntimeLifecycleCommandType.START, 1, "direct"),
    "no_network_delete": (RuntimeLifecycleCommandType.RESTART, 2, "no_network"),
    "no_network_start": (RuntimeLifecycleCommandType.START, 2, "no_network"),
    "reset": (RuntimeLifecycleCommandType.RESET, 3, "direct"),
    "reset_start": (RuntimeLifecycleCommandType.START, 3, "direct"),
    "delete": (RuntimeLifecycleCommandType.TERMINAL_DELETE, 4, "direct"),
}


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        raise RuntimeError(f"{name} is required")
    return value


def _runtime_configuration(
    *,
    desired_generation: int,
    network_mode: str,
) -> RuntimeConfigurationEnvelope:
    network_access: dict[str, JsonValue]
    if network_mode == "no_network":
        network_access = {"mode": "no_network"}
    else:
        network_access = {
            "mode": "direct",
            "allowed_cidrs": [],
            "denied_cidrs": [],
        }
    effective_profile: dict[str, JsonValue] = {
        "profile_kind": "kubernetes_pod",
        "contract_family": "kubernetes.pod-profile",
        "schema_version": 3,
        "runner_resources": {
            "cpu_request_millicores": 100,
            "cpu_limit_millicores": 2000,
            "memory_request_bytes": 536_870_912,
            "memory_limit_bytes": 4_294_967_296,
        },
        "workspace_volume": {
            "storage_class_name": _STORAGE_CLASS_NAME,
            "storage_request_bytes": 4_294_967_296,
        },
        "network_access": network_access,
        "service_account_name": None,
        "scheduling": {
            "node_selector": {},
            "tolerations": [],
        },
        "dind": None,
    }
    document: dict[str, JsonValue] = {
        "schema_version": 1,
        "provider": {
            "id": "nix-phase3-provider-resource",
            "logical_id": "nix-phase3-kubernetes",
            "kind": "kubernetes",
            "capability_revision_id": "nix-phase3-capability",
            "capability_digest": "a" * 64,
        },
        "infrastructure_profile": {
            "id": "nix-phase3-infrastructure",
            "version": 1,
            "digest": "b" * 64,
        },
        "workspace_runtime_profile": {
            "id": "nix-phase3-workspace-profile",
            "version": 1,
            "digest": "c" * 64,
        },
        "effective_profile": effective_profile,
    }
    return RuntimeConfigurationEnvelope(
        evidence=RuntimeConfigurationEvidence(
            configuration_sequence=desired_generation,
            digest=f"{desired_generation:x}" * 64,
            desired_generation=desired_generation,
        ),
        resolved_configuration_json=canonical_runtime_configuration_json(document),
    )


def _command(
    *,
    action: str,
    runner_image: str,
) -> RuntimeLifecycleCommand:
    command_type, desired_generation, network_mode = _ACTIONS[action]
    return RuntimeLifecycleCommand(
        command_type=command_type,
        identity=RuntimeIdentity(
            runtime_id=_RUNTIME_ID,
            agent_id="nix-phase3-agent",
            workspace_id="nix-phase3-workspace",
        ),
        desired_generation=desired_generation,
        provider_generation=1,
        runner_image=runner_image,
        auth=RuntimeContainerAuth(
            control_endpoint="runtime-control:8030",
            transfer_endpoint="runtime-control:8030",
            runner_auth_token=_required_env("PHASE3_RUNNER_AUTH_TOKEN"),
            runner_auth_credential_id=_required_env("PHASE3_RUNNER_AUTH_CREDENTIAL_ID"),
            control_tls_ca_pem=None,
            allow_insecure_control=True,
        ),
        reset_final_desired_state=(
            RuntimeDesiredState.RUNNING if action == "reset" else None
        ),
        runtime_configuration=_runtime_configuration(
            desired_generation=desired_generation,
            network_mode=network_mode,
        ),
    )


async def _run() -> None:
    runner_image = _required_env("PHASE3_RUNNER_IMAGE")
    action = _required_env("PHASE3_ACTION")
    if action not in _ACTIONS:
        raise RuntimeError(f"unsupported PHASE3_ACTION: {action}")
    settings = ProviderSettings()
    if settings.workspace_path != _WORKSPACE_PATH:
        raise RuntimeError("Phase 3 workspace path does not match the Runner contract")
    api = await KubernetesHttpApi.from_in_cluster()
    try:
        prepared = await prepare_runtime_provider(settings, api)
        registration = prepared.registration
        profile_contracts = registration.capability_contract.get("profile_contracts")
        if not isinstance(profile_contracts, list) or len(profile_contracts) != 1:
            raise RuntimeError("Provider registration has invalid Profile contracts")
        profile_contract = profile_contracts[0]
        if not isinstance(profile_contract, dict):
            raise RuntimeError("Provider registration has invalid Profile contract")
        if profile_contract.get("schema_versions") != [1, 2, 3]:
            raise RuntimeError("Provider registration does not advertise Profile v3")
        capabilities = profile_contract.get("capabilities")
        if not isinstance(capabilities, list) or not {
            "workspace.persistent-volume",
            "runtime.network-policy",
            "runtime.external-network-denial",
            "runtime.network-enforcement",
        }.issubset(capabilities):
            raise RuntimeError(
                "Provider registration lacks required Phase 3 capabilities"
            )

        provider = prepared.lifecycle
        command = _command(action=action, runner_image=runner_image)
        match action:
            case "start" | "recreate" | "no_network_start" | "reset_start":
                result = await provider.start(command)
            case "no_network_delete":
                result = await provider.restart(command)
            case "reset":
                result = await provider.reset(command)
            case "delete":
                result = await provider.terminal_delete(command)
            case _:
                raise AssertionError(action)
        sys.stdout.write(
            json.dumps(
                {
                    "action": action,
                    "configuration_sequence": (
                        result.report.runtime_configuration.configuration_sequence
                    ),
                    "network_mode": _ACTIONS[action][2],
                    "observed_state": result.report.observed_state.value,
                    "provider_runtime_id": result.report.provider_runtime_id,
                    "reason": result.report.reason,
                    "terminal_delete_acknowledged": (
                        result.report.terminal_delete_acknowledged
                    ),
                },
                sort_keys=True,
            )
            + "\n"
        )
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(_run())
