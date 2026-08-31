"""Bounded strict-network control-plane simulator for deterministic E2E."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import signal
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import docker
from azents_runtime_control.grpc_provider_client import (
    PROVIDER_AUTH_METHOD_AZENTS_ISSUED_TOKEN,
    GrpcProviderControlClient,
)
from azents_runtime_control.provider import (
    RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_ENFORCEMENT,
    JsonValue,
    ProviderRegistration,
    ProviderRunLoop,
    RuntimeDesiredState,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
    RuntimeLifecycleResult,
    RuntimeProviderObservedState,
    RuntimeProviderOperationalDiagnostics,
    RuntimeProviderReconciliationEvidence,
    RuntimeProviderReconciliationObservation,
    RuntimeProviderReconciliationStatus,
    RuntimeProviderReport,
)
from azents_runtime_control.runtime_configuration import (
    KubernetesPodProfileV3,
    RuntimeNetworkMode,
    parse_runtime_configuration_envelope,
    validate_runtime_configuration_cleanup_envelope,
)
from docker.errors import NotFound
from docker.models.containers import Container
from pydantic import BaseModel, ConfigDict, Field

_CONTROL_PLANE_CLASSIFICATION = "control_plane_only"
_MANAGED_BY_LABEL = "azents/control-plane-simulator"
_RUNTIME_ID_LABEL = "azents/runtime-id"
_PROVIDER_ID_LABEL = "azents/runtime-provider-id"
_WORKSPACE_PATH = "/workspace/agent"


class ControlPlaneEvidence(BaseModel):
    """One secret-free event that cannot represent packet enforcement."""

    model_config = ConfigDict(extra="forbid")

    classification: Literal["control_plane_only"]
    event: Literal["provider_registered", "command_completed"]
    provider_id: str = Field(min_length=1)
    command_type: str | None
    runtime_id: str | None
    network_mode: Literal["proxy_required", "no_network"] | None
    configuration_sequence: int | None
    desired_generation: int | None
    digest: str | None
    provider_acknowledgement: bool
    runner_process_started: bool
    recorded_at: datetime


@dataclasses.dataclass(frozen=True)
class StrictNetworkControlPlaneFixture:
    """Public fixture state containing no credentials or endpoints."""

    provider_id: str
    evidence_path: Path


def load_control_plane_evidence(path: Path) -> tuple[ControlPlaneEvidence, ...]:
    """Load bounded simulator evidence from JSON Lines."""
    if not path.exists():
        return ()
    return tuple(
        ControlPlaneEvidence.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


class StrictNetworkControlPlaneLifecycle:
    """Lifecycle simulator that starts real Runner containers without Kubernetes."""

    def __init__(
        self,
        *,
        provider_id: str,
        network_name: str,
        evidence_path: Path,
        workspace_root: Path,
    ) -> None:
        self.provider_id = provider_id
        self.network_name = network_name
        self.evidence_path = evidence_path
        self.workspace_root = workspace_root
        self.docker = docker.from_env()
        self.commands: dict[str, RuntimeLifecycleCommand] = {}
        self.runner_images: dict[str, str] = {}

    async def start(self, command: RuntimeLifecycleCommand) -> RuntimeLifecycleResult:
        """Start a Runner process and acknowledge only control-plane convergence."""
        self._validate_strict_command(command)
        await asyncio.to_thread(self._replace_runner, command)
        self.commands[command.identity.runtime_id] = command
        self._record_command(command, runner_process_started=True)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.START,
            report=self._report(
                command, observed_state=RuntimeProviderObservedState.RUNNING
            ),
        )

    async def stop(self, command: RuntimeLifecycleCommand) -> RuntimeLifecycleResult:
        """Remove the bounded Runner process while preserving its workspace."""
        self._validate_cleanup_command(command)
        await asyncio.to_thread(self._remove_runner, command.identity.runtime_id)
        self.commands[command.identity.runtime_id] = command
        self._record_command(command, runner_process_started=False)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.STOP,
            report=self._report(
                command, observed_state=RuntimeProviderObservedState.STOPPED
            ),
        )

    async def restart(self, command: RuntimeLifecycleCommand) -> RuntimeLifecycleResult:
        """Replace the bounded Runner process."""
        self._validate_strict_command(command)
        await asyncio.to_thread(self._replace_runner, command)
        self.commands[command.identity.runtime_id] = command
        self._record_command(command, runner_process_started=True)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.RESTART,
            report=self._report(
                command, observed_state=RuntimeProviderObservedState.RUNNING
            ),
        )

    async def reset(self, command: RuntimeLifecycleCommand) -> RuntimeLifecycleResult:
        """Reset the local test workspace and honor the explicit final state."""
        self._validate_strict_command(command)
        await asyncio.to_thread(self._remove_runner, command.identity.runtime_id)
        await asyncio.to_thread(
            self._delete_runtime_data,
            command.identity.runtime_id,
            image=command.runner_image,
        )
        runner_started = (
            command.reset_final_desired_state is RuntimeDesiredState.RUNNING
        )
        if runner_started:
            await asyncio.to_thread(self._replace_runner, command)
        self.commands[command.identity.runtime_id] = command
        self._record_command(command, runner_process_started=runner_started)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.RESET,
            report=self._report(
                command,
                observed_state=(
                    RuntimeProviderObservedState.RUNNING
                    if runner_started
                    else RuntimeProviderObservedState.STOPPED
                ),
            ),
        )

    async def update_configuration(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Replace the Runner so its exact configuration evidence changes."""
        self._validate_strict_command(command)
        await asyncio.to_thread(self._replace_runner, command)
        self.commands[command.identity.runtime_id] = command
        self._record_command(command, runner_process_started=True)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.UPDATE_CONFIGURATION,
            report=self._report(
                command, observed_state=RuntimeProviderObservedState.RUNNING
            ),
        )

    async def terminal_delete(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Remove all simulator-owned Runner state."""
        self._validate_cleanup_command(command)
        await asyncio.to_thread(self._remove_runner, command.identity.runtime_id)
        await asyncio.to_thread(
            self._delete_runtime_data,
            command.identity.runtime_id,
            image=command.runner_image,
        )
        self.commands.pop(command.identity.runtime_id, None)
        self.runner_images.pop(command.identity.runtime_id, None)
        self._record_command(command, runner_process_started=False)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.TERMINAL_DELETE,
            report=dataclasses.replace(
                self._report(
                    command,
                    observed_state=RuntimeProviderObservedState.STOPPED,
                ),
                terminal_delete_acknowledged=True,
            ),
        )

    async def observe(self, command: RuntimeLifecycleCommand) -> RuntimeProviderReport:
        """Observe only simulator-owned Runner process state."""
        self._validate_strict_command(command)
        running = await asyncio.to_thread(
            self._runner_running, command.identity.runtime_id
        )
        self.commands[command.identity.runtime_id] = command
        return self._report(
            command,
            observed_state=(
                RuntimeProviderObservedState.RUNNING
                if running
                else RuntimeProviderObservedState.STOPPED
            ),
        )

    async def observe_known_runtimes(self) -> Sequence[RuntimeProviderReport]:
        """Return no reconstructed reports because artifacts are not authority."""
        return ()

    def close(self) -> None:
        """Remove all bounded Runner containers and close the Docker client."""
        containers = self.docker.containers.list(
            all=True,
            filters={
                "label": [
                    f"{_MANAGED_BY_LABEL}=true",
                    f"{_PROVIDER_ID_LABEL}={self.provider_id}",
                ]
            },
        )
        for container in containers:
            container.remove(force=True)
        for runtime_id, image in tuple(self.runner_images.items()):
            self._delete_runtime_data(runtime_id, image=image)
        self.runner_images.clear()
        if self.workspace_root.exists():
            self.workspace_root.rmdir()
        self.docker.close()

    def _replace_runner(self, command: RuntimeLifecycleCommand) -> None:
        runtime_id = command.identity.runtime_id
        self._remove_runner(runtime_id)
        self.runner_images[runtime_id] = command.runner_image
        workspace = self._workspace_path(runtime_id)
        nix_root = self._nix_path(runtime_id)
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o777)
        nix_root.mkdir(parents=True, exist_ok=True)
        nix_root.chmod(0o777)
        evidence = command.runtime_configuration.evidence
        environment = {
            "AZ_RUNTIME_CONTROL_ENDPOINT": command.auth.control_endpoint,
            "AZ_RUNTIME_TRANSFER_ENDPOINT": command.auth.transfer_endpoint,
            "AZ_RUNTIME_CONTROL_ALLOW_INSECURE": str(
                command.auth.allow_insecure_control
            ).lower(),
            "AZ_RUNTIME_ID": command.identity.runtime_id,
            "AZ_AGENT_ID": command.identity.agent_id,
            "AZ_WORKSPACE_ID": command.identity.workspace_id,
            "AZ_RUNTIME_PROVIDER_ID": self.provider_id,
            "AZ_RUNTIME_PROVIDER_GENERATION": str(command.provider_generation),
            "AZ_RUNTIME_DESIRED_GENERATION": str(command.desired_generation),
            "AZ_RUNTIME_RUNNER_AUTH_TOKEN": command.auth.runner_auth_token,
            "AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID": (
                command.auth.runner_auth_credential_id
            ),
            "AZ_RUNTIME_CONFIGURATION_SEQUENCE": str(evidence.configuration_sequence),
            "AZ_RUNTIME_CONFIGURATION_DIGEST": evidence.digest,
            "AZ_RUNTIME_CONFIGURATION_DESIRED_GENERATION": str(
                evidence.desired_generation
            ),
            "HOME": _WORKSPACE_PATH,
        }
        if command.auth.control_tls_ca_pem is not None:
            environment["AZ_RUNTIME_CONTROL_TLS_CA_PEM"] = (
                command.auth.control_tls_ca_pem
            )
        self.docker.containers.run(
            command.runner_image,
            detach=True,
            name=self._container_name(command.identity.runtime_id),
            network=self.network_name,
            environment=environment,
            labels={
                _MANAGED_BY_LABEL: "true",
                _RUNTIME_ID_LABEL: command.identity.runtime_id,
                _PROVIDER_ID_LABEL: self.provider_id,
            },
            volumes={
                str(workspace): {"bind": _WORKSPACE_PATH, "mode": "rw"},
                str(nix_root): {"bind": "/nix", "mode": "rw"},
            },
            user="1000:1000",
            working_dir=_WORKSPACE_PATH,
        )

    def _remove_runner(self, runtime_id: str) -> None:
        try:
            container = self.docker.containers.get(self._container_name(runtime_id))
        except NotFound:
            return
        container.remove(force=True)

    def _runner_running(self, runtime_id: str) -> bool:
        try:
            container: Container = self.docker.containers.get(
                self._container_name(runtime_id)
            )
        except NotFound:
            return False
        container.reload()
        return container.status == "running"

    def _delete_runtime_data(self, runtime_id: str, *, image: str) -> None:
        runtime_root = self._runtime_path(runtime_id)
        if not runtime_root.exists():
            return
        self.docker.containers.run(
            image,
            command=["/bin/sh", "-ec", "find /runtime-data -mindepth 1 -delete"],
            remove=True,
            user="root",
            volumes={
                str(runtime_root): {"bind": "/runtime-data", "mode": "rw"},
            },
        )
        runtime_root.rmdir()

    def _workspace_path(self, runtime_id: str) -> Path:
        return self._runtime_path(runtime_id) / "workspace"

    def _nix_path(self, runtime_id: str) -> Path:
        return self._runtime_path(runtime_id) / "nix"

    def _runtime_path(self, runtime_id: str) -> Path:
        return self.workspace_root / runtime_id

    def _container_name(self, runtime_id: str) -> str:
        return f"azents-control-plane-runner-{runtime_id}"

    def _validate_strict_command(
        self, command: RuntimeLifecycleCommand
    ) -> Literal["proxy_required", "no_network"]:
        configuration = parse_runtime_configuration_envelope(
            command.runtime_configuration,
            desired_generation=command.desired_generation,
            expected_provider_kind="kubernetes",
        )
        if configuration.provider.logical_id != self.provider_id:
            raise ValueError("Runtime configuration is bound to another Provider")
        profile = configuration.effective_profile
        if not isinstance(profile, KubernetesPodProfileV3):
            raise ValueError("control-plane simulator requires Kubernetes Profile v3")
        mode = profile.network_access.mode
        if mode is RuntimeNetworkMode.PROXY_REQUIRED:
            return "proxy_required"
        if mode is RuntimeNetworkMode.NO_NETWORK:
            return "no_network"
        raise ValueError("control-plane simulator accepts strict network modes only")

    def _validate_cleanup_command(self, command: RuntimeLifecycleCommand) -> None:
        provider = validate_runtime_configuration_cleanup_envelope(
            command.runtime_configuration,
            desired_generation=command.desired_generation,
            expected_provider_kind="kubernetes",
        )
        if provider.logical_id != self.provider_id:
            raise ValueError("Runtime configuration is bound to another Provider")

    def _report(
        self,
        command: RuntimeLifecycleCommand,
        *,
        observed_state: RuntimeProviderObservedState,
    ) -> RuntimeProviderReport:
        return RuntimeProviderReport(
            runtime_id=command.identity.runtime_id,
            provider_id=self.provider_id,
            provider_generation=command.provider_generation,
            observed_state=observed_state,
            observed_desired_generation=command.desired_generation,
            provider_runtime_id=self._container_name(command.identity.runtime_id),
            reason="control_plane_simulated",
            diagnostic={"evidence_classification": _CONTROL_PLANE_CLASSIFICATION},
            reported_at=datetime.now(UTC),
            terminal_delete_acknowledged=False,
            runtime_configuration=command.runtime_configuration.evidence,
            reconciliation=RuntimeProviderReconciliationEvidence(
                observations=(
                    RuntimeProviderReconciliationObservation(
                        kind=(RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_ENFORCEMENT),
                        status=RuntimeProviderReconciliationStatus.IN_SYNC,
                        reason="control_plane_simulated",
                        diagnostic={
                            "evidence_classification": _CONTROL_PLANE_CLASSIFICATION
                        },
                    ),
                )
            ),
        )

    def _record_command(
        self,
        command: RuntimeLifecycleCommand,
        *,
        runner_process_started: bool,
    ) -> None:
        mode = self._validate_strict_command(command)
        evidence = command.runtime_configuration.evidence
        self._append_evidence(
            ControlPlaneEvidence(
                classification="control_plane_only",
                event="command_completed",
                provider_id=self.provider_id,
                command_type=command.command_type.value,
                runtime_id=command.identity.runtime_id,
                network_mode=mode,
                configuration_sequence=evidence.configuration_sequence,
                desired_generation=command.desired_generation,
                digest=evidence.digest,
                provider_acknowledgement=True,
                runner_process_started=runner_process_started,
                recorded_at=datetime.now(UTC),
            )
        )

    def _append_evidence(self, evidence: ControlPlaneEvidence) -> None:
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        with self.evidence_path.open("a", encoding="utf-8") as output:
            output.write(evidence.model_dump_json() + "\n")


async def run_control_plane_simulator(
    *,
    endpoint: str,
    provider_id: str,
    provider_credential: str,
    network_name: str,
    evidence_path: Path,
) -> None:
    """Run the bounded Provider loop until SIGINT or SIGTERM."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    client = GrpcProviderControlClient.from_endpoint(
        endpoint,
        provider_credential=provider_credential,
        provider_auth_method=PROVIDER_AUTH_METHOD_AZENTS_ISSUED_TOKEN,
        tls=None,
        allow_insecure=True,
    )
    workspace_root = Path(tempfile.mkdtemp(prefix="azents-control-plane-workspaces-"))
    lifecycle = StrictNetworkControlPlaneLifecycle(
        provider_id=provider_id,
        network_name=network_name,
        evidence_path=evidence_path,
        workspace_root=workspace_root,
    )
    registration = ProviderRegistration(
        provider_id=provider_id,
        provider_type="kubernetes",
        scope="system",
        workspace_id=None,
        protocol_version="agent-runtime-provider-kubernetes-v3",
        capabilities=(
            "lifecycle",
            "observe",
            "pvc_persistence",
            "network_enforcement_reconciliation",
        ),
        config_schema_version="agent-runtime-provider-kubernetes-v3",
        metadata={"evidence_classification": _CONTROL_PLANE_CLASSIFICATION},
        capability_contract=_capability_contract(),
        operational_diagnostics=None,
    )
    operational_diagnostics = RuntimeProviderOperationalDiagnostics(
        checked_at=datetime.now(UTC),
        warnings=(),
    )
    run_loop = ProviderRunLoop(
        client=client,
        lifecycle=lifecycle,
        registration=registration,
        connection_id=f"{provider_id}:{uuid.uuid4().hex}",
        consumer_id=f"{provider_id}:control-plane-simulator",
        operational_diagnostics=lambda: operational_diagnostics,
    )
    try:
        accepted = await run_loop.start()
        lifecycle._append_evidence(
            ControlPlaneEvidence(
                classification="control_plane_only",
                event="provider_registered",
                provider_id=provider_id,
                command_type=None,
                runtime_id=None,
                network_mode=None,
                configuration_sequence=None,
                desired_generation=None,
                digest=None,
                provider_acknowledgement=False,
                runner_process_started=False,
                recorded_at=datetime.now(UTC),
            )
        )
        if accepted.provider_id != provider_id:
            raise RuntimeError("Control accepted an unexpected Provider identity")
        await run_loop.run_forever(stop=stop, command_block_ms=500)
    finally:
        lifecycle.close()
        await client.close()


def _capability_contract() -> Mapping[str, JsonValue]:
    """Return the production-compatible v3 contract needed for composition."""
    return {
        "schema_version": 1,
        "implementation_key": "kubernetes",
        "implementation_version": "control-plane-e2e",
        "protocol_version": "agent-runtime-provider-kubernetes-v3",
        "core_lifecycle_operations": [
            "start",
            "stop",
            "restart",
            "reset",
            "observe",
            "terminal_delete",
        ],
        "optional_capabilities": [],
        "persistence": {
            "kind": "persistent",
            "reset_destroys_workspace": True,
            "terminal_delete_destroys_workspace": True,
        },
        "configuration_fields": [],
        "profile_contracts": [
            {
                "profile_kind": "kubernetes_pod",
                "contract_family": "kubernetes.pod-profile",
                "schema_versions": [3],
                "capabilities": [
                    "kubernetes.pod-profile",
                    "runtime.resources",
                    "workspace.persistent-volume",
                    "runtime.network-policy",
                    "kubernetes.service-account",
                    "kubernetes.scheduling",
                    "runtime.inspected-http-proxy",
                    "runtime.external-network-denial",
                    "runtime.network-enforcement",
                ],
                "constraints": {"maximums": {}, "allowed_values": {}},
            }
        ],
    }


def main() -> None:
    """Run the simulator from the deterministic E2E fixture."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--network-name", required=True)
    parser.add_argument("--evidence-path", type=Path, required=True)
    args = parser.parse_args()
    credential = os.environ["AZ_RUNTIME_PROVIDER_CREDENTIAL"]
    asyncio.run(
        run_control_plane_simulator(
            endpoint=args.endpoint,
            provider_id=args.provider_id,
            provider_credential=credential,
            network_name=args.network_name,
            evidence_path=args.evidence_path,
        )
    )


if __name__ == "__main__":
    main()
