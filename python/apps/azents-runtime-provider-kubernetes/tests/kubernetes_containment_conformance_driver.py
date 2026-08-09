"""Create one Runtime Pod through the production Kubernetes Provider boundary."""

import asyncio
import json
import os
import sys

from azents_runtime_control.provider import (
    RuntimeContainerAuth,
    RuntimeIdentity,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
)
from azents_runtime_control.runtime_configuration import (
    JsonValue,
    RuntimeConfigurationEnvelope,
    RuntimeConfigurationEvidence,
    canonical_runtime_configuration_json,
)

from azents_runtime_provider_kubernetes.kubernetes_http import KubernetesHttpApi
from azents_runtime_provider_kubernetes.main import (
    ProviderSettings,
    prepare_runtime_provider,
)

_WORKSPACE_PATH = "/runtime/home"


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        raise RuntimeError(f"{name} is required")
    return value


def _runtime_configuration(*, contained: bool) -> RuntimeConfigurationEnvelope:
    effective_profile: dict[str, JsonValue] = {
        "profile_kind": "kubernetes_pod",
        "contract_family": "kubernetes.pod-profile",
        "schema_version": 2,
        "runner_resources": {
            "cpu_request_millicores": 100,
            "cpu_limit_millicores": 1000,
            "memory_request_bytes": 268_435_456,
            "memory_limit_bytes": 1_073_741_824,
        },
        "workspace_volume": {
            "storage_class_name": "manual",
            "storage_request_bytes": 67_108_864,
        },
        "network_policy": {
            "allowed_cidrs": [],
            "denied_cidrs": [],
        },
        "service_account_name": None,
        "scheduling": {
            "node_selector": {},
            "tolerations": [],
        },
        "dind": None,
        "process_containment": {"schema_version": 1} if contained else None,
    }
    document: dict[str, JsonValue] = {
        "schema_version": 1,
        "provider": {
            "id": "phase5-provider-resource",
            "logical_id": "phase5-kubernetes",
            "kind": "kubernetes",
            "capability_revision_id": "phase5-capability",
            "capability_digest": "a" * 64,
        },
        "infrastructure_profile": {
            "id": "phase5-infrastructure",
            "version": 1,
            "digest": "b" * 64,
        },
        "workspace_runtime_profile": {
            "id": "phase5-workspace-profile",
            "version": 1,
            "digest": "c" * 64,
        },
        "effective_profile": effective_profile,
    }
    return RuntimeConfigurationEnvelope(
        evidence=RuntimeConfigurationEvidence(
            revision_id=("phase5-contained" if contained else "phase5-direct"),
            digest=("d" if contained else "e") * 64,
            desired_generation=1,
        ),
        resolved_configuration_json=canonical_runtime_configuration_json(document),
    )


async def _run() -> None:
    runner_image = _required_env("PHASE5_RUNNER_IMAGE")
    mode = _required_env("PHASE5_PROFILE_MODE")
    if mode not in {"contained", "direct"}:
        raise RuntimeError("PHASE5_PROFILE_MODE must be contained or direct")
    settings = ProviderSettings()
    api = await KubernetesHttpApi.from_in_cluster()
    try:
        prepared = await prepare_runtime_provider(settings, api)
        registration = prepared.registration
        profile_contracts = registration.capability_contract.get("profile_contracts")
        if not isinstance(profile_contracts, list) or len(profile_contracts) != 1:
            raise RuntimeError("Provider registration has invalid profile contracts")
        profile_contract = profile_contracts[0]
        if not isinstance(profile_contract, dict):
            raise RuntimeError("Provider registration has invalid profile contract")
        capabilities = profile_contract.get("capabilities")
        schema_versions = profile_contract.get("schema_versions")
        if (
            not isinstance(capabilities, list)
            or "runtime.process-containment" not in capabilities
            or schema_versions != [1, 2]
            or registration.metadata.get("process_containment_backend") != "bwrap"
            or registration.metadata.get("process_containment_runtime_class")
            != "phase5-runc"
        ):
            raise RuntimeError(
                "Provider registration does not advertise configured containment"
            )
        provider = prepared.lifecycle
        result = await provider.start(
            RuntimeLifecycleCommand(
                command_type=RuntimeLifecycleCommandType.START,
                identity=RuntimeIdentity(
                    runtime_id="phase5",
                    agent_id="phase5-agent",
                    workspace_id="phase5-workspace",
                ),
                desired_generation=1,
                provider_generation=1,
                runner_image=runner_image,
                auth=RuntimeContainerAuth(
                    control_endpoint="runtime-control:8030",
                    transfer_endpoint="runtime-control:8030",
                    runner_auth_token="phase5-runner-token",
                    runner_auth_credential_id="phase5-runner-credential",
                    control_tls_ca_pem=None,
                    allow_insecure_control=True,
                ),
                reset_final_desired_state=None,
                runtime_configuration=_runtime_configuration(
                    contained=mode == "contained"
                ),
            )
        )
        evidence = json.dumps(
            {
                "observed_state": result.report.observed_state.value,
                "reason": result.report.reason,
                "profile_mode": mode,
                "registration_metadata": dict(registration.metadata),
            },
            sort_keys=True,
        )
        sys.stdout.write(f"{evidence}\n")
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(_run())
