"""Agent Runtime desired-state reconciliation."""

import dataclasses
import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as RuntimeProviderCommandType,
)
from azents_runtime_control.runtime_configuration import (
    RuntimeConfigurationEnvelope,
    RuntimeConfigurationEvidence,
    canonical_runtime_configuration_json,
    parse_runtime_configuration_envelope,
)
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationApplicationImpact,
    RuntimeConfigurationResolutionStatus,
    classify_runtime_configuration_application,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeFailurePatch
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
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
    runner_transfer_endpoint: str
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
        profile_repository: RuntimeProfileRepository,
        session_manager: SessionManager[AsyncSession],
        coordination_store: RuntimeCoordinationStore,
        control_protocol: RuntimeControlProtocolService,
        config: RuntimeLifecycleDispatchConfig,
    ) -> None:
        """Initialize the reconciler."""
        self._runtime_repository = runtime_repository
        self._profile_repository = profile_repository
        self._session_manager = session_manager
        self._coordination_store = coordination_store
        self._control_protocol = control_protocol
        self._config = config

    async def reconcile_once(self, *, limit: int = _DEFAULT_LIMIT) -> int:
        """Dispatch one batch of pending lifecycle commands."""
        async with self._session_manager() as session:
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
            configuration_runtimes = (
                await self._runtime_repository.find_configuration_adoption_candidates(
                    session,
                    limit=limit,
                )
            )

        dispatched = 0
        for runtime in runtimes:
            if await self._dispatch_runtime(runtime):
                dispatched += 1
        lifecycle_runtime_ids = {runtime.id for runtime in runtimes}
        configuration_runtime_ids = {runtime.id for runtime in configuration_runtimes}
        for runtime in configuration_runtimes:
            if runtime.id in lifecycle_runtime_ids:
                continue
            if await self._dispatch_configuration_adoption(runtime):
                dispatched += 1
        for runtime in reconcile_runtimes:
            if (
                runtime.id in lifecycle_runtime_ids
                or runtime.id in configuration_runtime_ids
            ):
                continue
            if await self._dispatch_periodic_reconcile(runtime):
                dispatched += 1

        # A persisted CONNECTED flag can outlive the Control process that owned the
        # actual Provider stream. Give the current coordination registry a chance to
        # refresh that cache (or dispatch and refresh the start timer) before turning
        # an old start attempt into a terminal timeout.
        async with self._session_manager() as session:
            timed_out = await self._runtime_repository.mark_start_timeouts(
                session,
                stale_threshold=self._config.start_timeout,
                limit=limit,
            )
        if timed_out:
            _LOGGER.warning(
                "Runtime lifecycle start timed out",
                extra={
                    "count": len(timed_out),
                    "start_timeout_seconds": (
                        self._config.start_timeout.total_seconds()
                    ),
                },
            )
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
        if (
            runtime.desired_state is RuntimeDesiredState.RUNNING
            and runtime.provider_observed_state is RuntimeProviderObservedState.RUNNING
            and runtime.applied_runtime_configuration_revision_id is not None
            and runtime.desired_runtime_configuration_revision_id
            != runtime.applied_runtime_configuration_revision_id
        ):
            return False
        async with self._session_manager() as session:
            await self._runtime_repository.mark_provider_observe_requested(
                session,
                runtime.id,
            )
        command_type = (
            RuntimeProviderCommandType.START
            if (
                runtime.desired_state is RuntimeDesiredState.RUNNING
                and runtime.provider_observed_state
                in {
                    RuntimeProviderObservedState.UNKNOWN,
                    RuntimeProviderObservedState.STOPPED,
                }
            )
            else RuntimeProviderCommandType.OBSERVE
        )
        return await self._dispatch_runtime_command(
            runtime,
            command_type=command_type,
            claim_lifecycle=False,
        )

    async def _dispatch_configuration_adoption(
        self,
        runtime: AgentRuntime,
    ) -> bool:
        desired_revision_id = runtime.desired_runtime_configuration_revision_id
        applied_revision_id = runtime.applied_runtime_configuration_revision_id
        if desired_revision_id is None or applied_revision_id is None:
            return False
        async with self._session_manager() as session:
            desired = await self._profile_repository.get_configuration_revision(
                session,
                revision_id=desired_revision_id,
            )
            applied = await self._profile_repository.get_configuration_revision(
                session,
                revision_id=applied_revision_id,
            )
        if desired is None or applied is None:
            return False
        impact = classify_runtime_configuration_application(
            desired_status=desired.resolution_status,
            desired_configuration=desired.resolved_configuration,
            applied_configuration=applied.resolved_configuration,
        )
        if impact is not RuntimeConfigurationApplicationImpact.IN_PLACE:
            return False
        if (
            desired.provider_acknowledged_at is None
            or desired.provider_reported_digest != desired.digest
        ):
            return await self._dispatch_runtime_command(
                runtime,
                command_type=RuntimeProviderCommandType.UPDATE_CONFIGURATION,
                claim_lifecycle=False,
            )
        return False

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
            runtime_configuration = await self._runtime_configuration(
                runtime,
                require_ready=command_type
                not in {
                    RuntimeProviderCommandType.STOP,
                    RuntimeProviderCommandType.TERMINAL_DELETE,
                    RuntimeProviderCommandType.OBSERVE,
                },
            )
        except ValueError as error:
            await self._record_failure(
                runtime,
                code="RUNTIME_CONFIGURATION_INVALID",
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
                        "transfer_endpoint": self._config.runner_transfer_endpoint,
                        "runner_auth_credential_id": runner_credential_id,
                        "control_tls_ca_pem": (self._config.runner_control_tls_ca_pem),
                        "allow_insecure_control": (
                            self._config.allow_insecure_runner_control
                        ),
                    },
                },
                deadline_at=created_at + self._config.provider_command_deadline,
                runtime_configuration=runtime_configuration,
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

    async def _runtime_configuration(
        self,
        runtime: AgentRuntime,
        *,
        require_ready: bool = True,
    ) -> RuntimeConfigurationEnvelope:
        revision_id = (
            runtime.desired_runtime_configuration_revision_id
            if require_ready
            else (
                runtime.desired_runtime_configuration_revision_id
                or runtime.applied_runtime_configuration_revision_id
            )
        )
        if revision_id is None:
            raise ValueError("Runtime configuration target revision is missing.")
        async with self._session_manager() as session:
            revision = await self._profile_repository.get_configuration_revision(
                session,
                revision_id=revision_id,
            )
        if revision is None:
            raise ValueError("Runtime configuration target revision is missing.")
        if revision.runtime_id != runtime.id:
            raise ValueError("Runtime configuration revision ownership is invalid.")
        if (
            runtime.runtime_provider_resource_id is None
            or revision.provider_id != runtime.runtime_provider_resource_id
        ):
            raise ValueError("Runtime configuration Provider binding is invalid.")
        if require_ready:
            if revision.target_desired_generation != runtime.desired_generation:
                raise ValueError("Runtime configuration target generation is stale.")
            if (
                revision.resolution_status
                is not RuntimeConfigurationResolutionStatus.READY
            ):
                raise ValueError("Runtime configuration target revision is blocked.")
            if revision.resolved_configuration is None:
                raise ValueError("Runtime configuration target document is missing.")
        envelope = RuntimeConfigurationEnvelope(
            evidence=RuntimeConfigurationEvidence(
                revision_id=revision.id,
                digest=revision.digest,
                desired_generation=revision.target_desired_generation,
            ),
            resolved_configuration_json=canonical_runtime_configuration_json(
                revision.resolved_configuration or {}
            ),
        )
        if not require_ready:
            return envelope
        configuration = parse_runtime_configuration_envelope(
            envelope,
            desired_generation=runtime.desired_generation,
            expected_provider_kind=None,
        )
        if (
            configuration.provider.id != revision.provider_id
            or configuration.provider.logical_id != runtime.runtime_provider_id
            or configuration.provider.capability_revision_id
            != revision.provider_capability_revision_id
        ):
            raise ValueError("Runtime configuration Provider reference is invalid.")
        if (
            revision.infrastructure_profile_id != runtime.infrastructure_profile_id
            or configuration.infrastructure_profile.id
            != revision.infrastructure_profile_id
            or configuration.infrastructure_profile.version
            != revision.infrastructure_profile_version
        ):
            raise ValueError(
                "Runtime configuration Infrastructure Profile reference is invalid."
            )
        if (
            revision.workspace_runtime_profile_id
            != runtime.workspace_runtime_profile_id
            or configuration.workspace_runtime_profile.id
            != revision.workspace_runtime_profile_id
            or configuration.workspace_runtime_profile.version
            != revision.workspace_runtime_profile_version
        ):
            raise ValueError(
                "Runtime configuration Workspace Runtime Profile reference is invalid."
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
