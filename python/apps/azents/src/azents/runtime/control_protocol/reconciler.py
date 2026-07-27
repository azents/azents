"""Agent Runtime desired-state reconciliation."""

import dataclasses
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

from azents_runtime_control.execution_policy import (
    RuntimeExecutionPolicyEnvelope,
    RuntimeExecutionPolicyEvidence,
    parse_execution_policy_envelope,
)
from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as RuntimeProviderCommandType,
)
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeFailurePatch
from azents.repos.runtime_provider_policy.data import RuntimePolicySnapshot
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeProtocolRouteUnavailable,
    RuntimeProtocolStaleGeneration,
    RuntimeProviderCommand,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.data import RuntimeConnectionKind
from azents.runtime.coordination.store import RuntimeCoordinationStore

_DEFAULT_LIMIT = 100
_DEFAULT_PROVIDER_COMMAND_DEADLINE = timedelta(seconds=10)
_DEFAULT_OBSERVE_INTERVAL = timedelta(seconds=10)
_DEFAULT_LIFECYCLE_RETRY_DELAY = timedelta(seconds=15)
_DEFAULT_START_TIMEOUT = timedelta(minutes=5)
_LOGGER = logging.getLogger(__name__)


class RuntimeRunnerCredentialIdentifier(Protocol):
    """Derive the non-secret ID for Runtime Runner evidence."""

    def credential_id(
        self,
        *,
        runtime_id: str,
        desired_generation: int,
    ) -> str:
        """Return the non-secret Runner credential identifier."""
        ...


@dataclasses.dataclass(frozen=True)
class RuntimeLifecycleDispatchConfig:
    """Config required to dispatch lifecycle commands to Providers."""

    runner_image: str
    runner_control_endpoint: str
    runner_credential_identifier: RuntimeRunnerCredentialIdentifier
    runner_control_tls_ca_pem: str | None
    allow_insecure_runner_control: bool
    start_timeout: timedelta = _DEFAULT_START_TIMEOUT
    provider_command_deadline: timedelta = _DEFAULT_PROVIDER_COMMAND_DEADLINE
    observe_interval: timedelta = _DEFAULT_OBSERVE_INTERVAL
    lifecycle_retry_delay: timedelta = _DEFAULT_LIFECYCLE_RETRY_DELAY


class RuntimeLifecycleReconciler:
    """Dispatch durable desired-state changes to connected Runtime Providers."""

    def __init__(
        self,
        *,
        runtime_repository: AgentRuntimeRepository,
        policy_repository: RuntimeProviderPolicyRepository,
        session_manager: SessionManager[AsyncSession],
        coordination_store: RuntimeCoordinationStore,
        control_protocol: RuntimeControlProtocolService,
        config: RuntimeLifecycleDispatchConfig,
    ) -> None:
        """Initialize the reconciler."""
        self._runtime_repository = runtime_repository
        self._policy_repository = policy_repository
        self._session_manager = session_manager
        self._coordination_store = coordination_store
        self._control_protocol = control_protocol
        self._config = config

    async def reconcile_once(self, *, limit: int = _DEFAULT_LIMIT) -> int:
        """Dispatch one batch of pending lifecycle commands."""
        async with self._session_manager() as session:
            timed_out = await self._runtime_repository.mark_start_timeouts(
                session,
                stale_threshold=self._config.start_timeout,
                limit=limit,
            )
            runtimes = (
                await self._runtime_repository.find_lifecycle_dispatch_candidates(
                    session,
                    limit=limit,
                    retry_delay=self._config.lifecycle_retry_delay,
                )
            )
            reconcile_runtimes = (
                await self._runtime_repository.find_provider_observe_candidates(
                    session,
                    limit=limit,
                    observe_interval=self._config.observe_interval,
                )
            )

        if timed_out:
            _LOGGER.warning(
                "Runtime lifecycle start timed out",
                extra={
                    "count": len(timed_out),
                    "start_timeout_seconds": self._config.start_timeout.total_seconds(),
                },
            )
        dispatched = 0
        for runtime in runtimes:
            if await self._dispatch_runtime(runtime):
                dispatched += 1
        lifecycle_runtime_ids = {runtime.id for runtime in runtimes}
        for runtime in reconcile_runtimes:
            if runtime.id in lifecycle_runtime_ids:
                continue
            if await self._dispatch_periodic_reconcile(runtime):
                dispatched += 1
        return dispatched

    async def _dispatch_runtime(self, runtime: AgentRuntime) -> bool:
        command_type = _provider_command_type(runtime)
        if command_type is None:
            return False
        return await self._dispatch_runtime_command(
            runtime,
            command_type=command_type,
            claim_lifecycle=True,
        )

    async def _dispatch_periodic_reconcile(self, runtime: AgentRuntime) -> bool:
        async with self._session_manager() as session:
            await self._runtime_repository.mark_provider_observe_requested(
                session,
                runtime.id,
            )
        command_type = (
            RuntimeProviderCommandType.START
            if runtime.desired_state is RuntimeDesiredState.RUNNING
            else RuntimeProviderCommandType.OBSERVE
        )
        return await self._dispatch_runtime_command(
            runtime,
            command_type=command_type,
            claim_lifecycle=False,
        )

    async def _dispatch_runtime_command(
        self,
        runtime: AgentRuntime,
        *,
        command_type: RuntimeProviderCommandType,
        claim_lifecycle: bool,
    ) -> bool:
        provider_id = runtime.runtime_provider_id
        if provider_id is None:
            _LOGGER.warning(
                "Runtime lifecycle dispatch skipped without provider",
                extra={
                    "runtime_id": runtime.id,
                    "agent_id": runtime.agent_id,
                    "desired_generation": runtime.desired_generation,
                },
            )
            await self._record_failure(
                runtime,
                code="PROVIDER_NOT_CONFIGURED",
                message="Agent Runtime has no configured Runtime Provider.",
            )
            return False
        connection = await self._coordination_store.get_connection(
            kind=RuntimeConnectionKind.PROVIDER,
            subject_id=provider_id,
        )
        if connection is None:
            _LOGGER.warning(
                "Runtime lifecycle dispatch waiting for provider connection",
                extra={
                    "runtime_id": runtime.id,
                    "agent_id": runtime.agent_id,
                    "provider_id": provider_id,
                    "desired_generation": runtime.desired_generation,
                    "command_type": command_type.value,
                },
            )
            async with self._session_manager() as session:
                await self._runtime_repository.record_provider_connection_state(
                    session,
                    runtime.id,
                    RuntimeProviderConnectionState.DISCONNECTED,
                )
            return False

        if claim_lifecycle:
            async with self._session_manager() as session:
                claimed = await self._runtime_repository.claim_lifecycle_dispatch(
                    session,
                    runtime.id,
                    runtime.desired_generation,
                    retry_delay=self._config.provider_command_deadline,
                )
            if claimed is None:
                _LOGGER.debug(
                    "Runtime lifecycle dispatch skipped after concurrent claim",
                    extra={
                        "runtime_id": runtime.id,
                        "agent_id": runtime.agent_id,
                        "provider_id": provider_id,
                        "desired_generation": runtime.desired_generation,
                        "command_type": command_type.value,
                    },
                )
                return False
            runtime = claimed

        created_at = datetime.now(UTC)
        runner_credential_id = self._config.runner_credential_identifier.credential_id(
            runtime_id=runtime.id,
            desired_generation=runtime.desired_generation,
        )
        try:
            execution_policy = await self._execution_policy(runtime)
        except ValueError as error:
            await self._record_failure(
                runtime,
                code="RUNTIME_EXECUTION_POLICY_INVALID",
                message=str(error),
            )
            return False
        result = await self._control_protocol.dispatch_provider_command(
            RuntimeProviderCommand(
                provider_id=provider_id,
                provider_generation=connection.generation,
                runtime_id=runtime.id,
                desired_generation=runtime.desired_generation,
                command_type=command_type,
                reset_final_desired_state=_reset_final_desired_state(runtime),
                payload={
                    "identity": {
                        "runtime_id": runtime.id,
                        "agent_id": runtime.agent_id,
                        "workspace_id": runtime.workspace_id,
                    },
                    "runner_image": self._config.runner_image,
                    "auth": {
                        "control_endpoint": self._config.runner_control_endpoint,
                        "runner_auth_credential_id": runner_credential_id,
                        "control_tls_ca_pem": (self._config.runner_control_tls_ca_pem),
                        "allow_insecure_control": (
                            self._config.allow_insecure_runner_control
                        ),
                    },
                },
                deadline_at=created_at + self._config.provider_command_deadline,
                execution_policy=execution_policy,
            ),
            created_at=created_at,
        )
        if isinstance(result, RuntimeDispatchResult):
            async with self._session_manager() as session:
                await self._runtime_repository.record_provider_connection_state(
                    session,
                    runtime.id,
                    RuntimeProviderConnectionState.CONNECTED,
                )
            _LOGGER.info(
                "Runtime lifecycle command dispatched",
                extra={
                    "runtime_id": runtime.id,
                    "agent_id": runtime.agent_id,
                    "provider_id": provider_id,
                    "provider_generation": connection.generation,
                    "desired_generation": runtime.desired_generation,
                    "command_type": command_type.value,
                    "request_id": result.request_id,
                },
            )
            return True
        if isinstance(result, RuntimeProtocolRouteUnavailable):
            _LOGGER.warning(
                "Runtime lifecycle dispatch route unavailable",
                extra={
                    "runtime_id": runtime.id,
                    "agent_id": runtime.agent_id,
                    "provider_id": provider_id,
                    "desired_generation": runtime.desired_generation,
                    "command_type": command_type.value,
                },
            )
            async with self._session_manager() as session:
                await self._runtime_repository.record_provider_connection_state(
                    session,
                    runtime.id,
                    RuntimeProviderConnectionState.DISCONNECTED,
                )
            return False
        if isinstance(result, RuntimeProtocolStaleGeneration):
            _LOGGER.info(
                "Runtime lifecycle dispatch skipped for stale provider generation",
                extra={
                    "runtime_id": runtime.id,
                    "agent_id": runtime.agent_id,
                    "provider_id": provider_id,
                    "provider_generation": connection.generation,
                    "desired_generation": runtime.desired_generation,
                    "command_type": command_type.value,
                },
            )
            return False
        raise AssertionError(f"unexpected dispatch result: {result!r}")

    async def _execution_policy(
        self,
        runtime: AgentRuntime,
    ) -> RuntimeExecutionPolicyEnvelope:
        snapshot_id = runtime.runtime_policy_snapshot_id
        if snapshot_id is None:
            raise ValueError("Runtime execution-policy target snapshot is missing.")
        async with self._session_manager() as session:
            snapshot = await self._policy_repository.get_snapshot(
                session,
                snapshot_id=snapshot_id,
                for_update=False,
            )
        if snapshot is None:
            raise ValueError("Runtime execution-policy target snapshot is missing.")
        if snapshot.runtime_id != runtime.id:
            raise ValueError("Runtime execution-policy snapshot ownership is invalid.")
        if (
            runtime.runtime_provider_resource_id is None
            or snapshot.provider_id != runtime.runtime_provider_resource_id
        ):
            raise ValueError("Runtime execution-policy Provider binding is invalid.")
        if snapshot.target_desired_generation != runtime.desired_generation:
            raise ValueError("Runtime execution-policy target generation is stale.")
        if snapshot.resolved_execution_policy_json is None:
            raise ValueError("Runtime execution-policy target document is missing.")
        envelope = RuntimeExecutionPolicyEnvelope(
            evidence=_snapshot_policy_evidence(snapshot),
            effective_policy_json=snapshot.resolved_execution_policy_json,
        )
        parse_execution_policy_envelope(
            envelope,
            desired_generation=runtime.desired_generation,
        )
        return envelope

    async def _record_failure(
        self,
        runtime: AgentRuntime,
        *,
        code: str,
        message: str,
    ) -> None:
        async with self._session_manager() as session:
            await self._runtime_repository.record_runtime_failure(
                session,
                runtime.id,
                AgentRuntimeFailurePatch(
                    generation=runtime.desired_generation,
                    code=code,
                    message=message,
                ),
            )


def _reset_final_desired_state(runtime: AgentRuntime) -> str | None:
    if runtime.last_lifecycle_command != RuntimeLifecycleCommandType.RESET:
        return None
    if runtime.reset_final_desired_state is None:
        return None
    return runtime.reset_final_desired_state.value


def _provider_command_type(
    runtime: AgentRuntime,
) -> RuntimeProviderCommandType | None:
    if (
        runtime.terminal_delete_requested_generation == runtime.desired_generation
        and runtime.terminal_delete_acknowledged_generation
        != runtime.desired_generation
    ):
        return RuntimeProviderCommandType.TERMINAL_DELETE
    if runtime.last_lifecycle_command is None:
        return None
    return RuntimeProviderCommandType(runtime.last_lifecycle_command.value)


def _snapshot_policy_evidence(
    snapshot: RuntimePolicySnapshot,
) -> RuntimeExecutionPolicyEvidence:
    source_versions = {
        "profile": snapshot.execution_profile_version,
        "workspace": snapshot.execution_workspace_version,
        "agent": snapshot.execution_agent_version,
    }
    if (
        snapshot.execution_target_digest is None
        or snapshot.resolved_execution_policy_json is None
        or any(version is None for version in source_versions.values())
    ):
        raise ValueError("Runtime execution-policy snapshot evidence is incomplete.")
    module_versions: dict[str, int] = {}
    policy = json.loads(snapshot.resolved_execution_policy_json)
    if not isinstance(policy, dict):
        raise ValueError("Runtime execution-policy snapshot must contain an object.")
    for value in policy.values():
        if not isinstance(value, dict):
            continue
        module_id = value.get("module_id")
        version = value.get("version")
        if isinstance(module_id, str) and isinstance(version, int):
            module_versions[module_id] = version
    return RuntimeExecutionPolicyEvidence(
        snapshot_id=snapshot.id,
        digest=snapshot.execution_target_digest,
        desired_generation=snapshot.target_desired_generation,
        module_versions=module_versions,
        source_versions={
            key: version
            for key, version in source_versions.items()
            if version is not None
        },
    )
