"""Agent Runtime desired-state reconciliation."""

import dataclasses
import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

from azents_runtime_control.provider import (
    RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_ENFORCEMENT,
    RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_POLICY,
    RuntimeProviderReport,
)
from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as RuntimeProviderCommandType,
)
from azents_runtime_control.provider import (
    RuntimeProviderReconciliationStatus as SharedProviderReconciliationStatus,
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
    RuntimeConfigurationStateStatus,
    classify_runtime_configuration_application,
)
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_lifecycle_dispatch.data import (
    RuntimeLifecycleDispatchAdmission,
    RuntimeLifecycleDispatchRejection,
    RuntimeLifecycleDispatchRejectionReason,
    RuntimeLifecycleDispatchRequest,
)
from azents.repos.runtime_lifecycle_dispatch.repository import (
    RuntimeLifecycleDispatchRepository,
)
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
        agent_repository: AgentRepository,
        runtime_repository: AgentRuntimeRepository,
        profile_repository: RuntimeProfileRepository,
        session_manager: SessionManager[AsyncSession],
        dispatch_repository: RuntimeLifecycleDispatchRepository,
        coordination_store: RuntimeCoordinationStore,
        control_protocol: RuntimeControlProtocolService,
        config: RuntimeLifecycleDispatchConfig,
    ) -> None:
        """Initialize the reconciler."""
        self._agent_repository = agent_repository
        self._runtime_repository = runtime_repository
        self._profile_repository = profile_repository
        self._session_manager = session_manager
        self._dispatch_repository = dispatch_repository
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
        configuration_dispatch_ids: set[str] = set()
        for runtime in configuration_runtimes:
            if runtime.id in lifecycle_runtime_ids:
                continue
            if await self._dispatch_configuration_adoption(runtime):
                dispatched += 1
                configuration_dispatch_ids.add(runtime.id)
        for runtime in reconcile_runtimes:
            if (
                runtime.id in lifecycle_runtime_ids
                or runtime.id in configuration_dispatch_ids
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
            required_provider_generation=None,
        )

    async def _dispatch_periodic_reconcile(self, runtime: AgentRuntime) -> bool:
        async with self._session_manager() as session:
            state = await self._profile_repository.get_configuration_state(
                session,
                runtime_id=runtime.id,
            )
            if (
                runtime.desired_state is RuntimeDesiredState.RUNNING
                and runtime.provider_observed_state
                is RuntimeProviderObservedState.RUNNING
                and state is not None
                and state.desired.status is RuntimeConfigurationStateStatus.READY
                and state.applied is not None
                and state.desired.sequence != state.applied.sequence
                and state.desired.provider_acknowledged_at is not None
                and state.desired.provider_reported_digest == state.desired.digest
            ):
                return False
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
            required_provider_generation=None,
        )

    async def _dispatch_configuration_adoption(
        self,
        runtime: AgentRuntime,
    ) -> bool:
        async with self._session_manager() as session:
            state = await self._profile_repository.get_configuration_state(
                session,
                runtime_id=runtime.id,
            )
        if state is None or state.applied is None:
            return False
        desired = state.desired
        applied = state.applied
        impact = classify_runtime_configuration_application(
            desired_status=(
                RuntimeConfigurationResolutionStatus.READY
                if desired.status is RuntimeConfigurationStateStatus.READY
                else RuntimeConfigurationResolutionStatus.BLOCKED
            ),
            desired_configuration=(
                desired.document.resolved_configuration
                if desired.document is not None
                else None
            ),
            applied_configuration=applied.document.resolved_configuration,
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
                required_provider_generation=None,
            )
        return False

    async def reconcile_observe_completion(
        self,
        report: RuntimeProviderReport,
    ) -> bool:
        """Immediately repair one current actionable network drift observation.

        This method is invoked only by the gRPC stream for a correlated successful
        ``OBSERVE`` completion. It deliberately retains no repair state: lost
        completions, restarts, and failed dispatches are retried only by a later
        periodic observation.
        """
        evidence = report.reconciliation
        if evidence is None:
            return False
        if len(evidence.observations) != 1:
            return False
        observation = evidence.observations[0]
        if (
            observation.kind
            not in {
                RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_POLICY,
                RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_ENFORCEMENT,
            }
            or observation.status is not SharedProviderReconciliationStatus.DRIFTED
        ):
            return False
        repair_target: AgentRuntime | None = None
        async with self._session_manager() as session:
            runtime = await self._runtime_repository.get_by_id(
                session,
                report.runtime_id,
            )
            if (
                runtime is None
                or runtime.runtime_provider_id != report.provider_id
                or runtime.runtime_provider_resource_id is None
                or runtime.desired_state is not RuntimeDesiredState.RUNNING
                or runtime.provider_observed_state
                is not RuntimeProviderObservedState.RUNNING
                or runtime.provider_generation != report.provider_generation
                or runtime.provider_observed_generation
                != report.observed_desired_generation
                or runtime.desired_generation != report.observed_desired_generation
            ):
                return False
            state = await self._profile_repository.get_configuration_state(
                session,
                runtime_id=runtime.id,
            )
            if (
                state is None
                or state.applied is None
                or state.desired.status is not RuntimeConfigurationStateStatus.READY
                or state.desired.sequence != state.applied.sequence
                or state.desired.sequence
                != report.runtime_configuration.configuration_sequence
            ):
                return False
            evidence_matches_current = (
                await self._profile_repository.configuration_evidence_matches_current(
                    session,
                    runtime_id=runtime.id,
                    provider_id=runtime.runtime_provider_resource_id,
                    evidence=report.runtime_configuration,
                )
            )
            if not evidence_matches_current:
                return False
            repair_target = runtime
        assert repair_target is not None
        _LOGGER.info(
            "Runtime network enforcement drift repair handed off",
            extra={
                "runtime_id": repair_target.id,
                "provider_id": report.provider_id,
                "provider_generation": report.provider_generation,
                "desired_generation": report.observed_desired_generation,
                "configuration_sequence": (
                    report.runtime_configuration.configuration_sequence
                ),
                "reconciliation_kind": observation.kind,
                "reconciliation_reason": observation.reason,
            },
        )
        return await self._dispatch_runtime_command(
            repair_target,
            command_type=RuntimeProviderCommandType.UPDATE_CONFIGURATION,
            claim_lifecycle=False,
            required_provider_generation=report.provider_generation,
            required_observed_generation=report.observed_desired_generation,
            required_configuration_sequence=(
                report.runtime_configuration.configuration_sequence
            ),
            reconciliation_kind=observation.kind,
            reconciliation_reason=observation.reason,
        )

    async def _dispatch_runtime_command(
        self,
        runtime: AgentRuntime,
        *,
        command_type: RuntimeProviderCommandType,
        claim_lifecycle: bool,
        required_provider_generation: int | None,
        required_observed_generation: int | None = None,
        required_configuration_sequence: int | None = None,
        reconciliation_kind: str | None = None,
        reconciliation_reason: str | None = None,
    ) -> bool:
        preflight_result = await self._dispatch_repository.preflight(
            RuntimeLifecycleDispatchRequest(
                runtime=runtime,
                command_type=command_type,
                claim_lifecycle=claim_lifecycle,
                required_provider_generation=required_provider_generation,
                required_observed_generation=required_observed_generation,
                required_configuration_sequence=required_configuration_sequence,
                lifecycle_retry_delay=self._config.lifecycle_retry_delay,
            )
        )
        if isinstance(preflight_result, RuntimeLifecycleDispatchRejection):
            if (
                preflight_result.reason
                is RuntimeLifecycleDispatchRejectionReason.PROVIDER_NOT_CONFIGURED
            ):
                _LOGGER.warning(
                    "Runtime lifecycle dispatch skipped without provider",
                    extra={
                        "runtime_id": runtime.id,
                        "agent_id": runtime.agent_id,
                        "desired_generation": runtime.desired_generation,
                    },
                )
            return False
        preflight = preflight_result
        provider_id = preflight.provider_id
        connection = await self._coordination_store.get_connection(
            kind=RuntimeConnectionKind.PROVIDER,
            subject_id=provider_id,
        )
        if connection is None:
            _LOGGER.warning(
                "Runtime lifecycle dispatch waiting for provider connection",
                extra={
                    "runtime_id": preflight.runtime_id,
                    "agent_id": preflight.agent_id,
                    "provider_id": provider_id,
                    "desired_generation": preflight.desired_generation,
                    "command_type": command_type.value,
                },
            )
            await self._dispatch_repository.record_connection_outcome(
                preflight,
                RuntimeProviderConnectionState.DISCONNECTED,
            )
            return False
        if (
            required_provider_generation is not None
            and connection.generation != required_provider_generation
        ):
            _LOGGER.info(
                "Runtime lifecycle dispatch skipped after Provider generation changed",
                extra={
                    "runtime_id": preflight.runtime_id,
                    "agent_id": preflight.agent_id,
                    "provider_id": provider_id,
                    "required_provider_generation": required_provider_generation,
                    "connection_provider_generation": connection.generation,
                    "desired_generation": preflight.desired_generation,
                    "command_type": command_type.value,
                },
            )
            return False
        admission_result = await self._dispatch_repository.claim(
            preflight,
            connection_generation=connection.generation,
        )
        if isinstance(admission_result, RuntimeLifecycleDispatchRejection):
            if (
                admission_result.reason
                is RuntimeLifecycleDispatchRejectionReason.LIFECYCLE_CLAIM_UNAVAILABLE
            ):
                _LOGGER.debug(
                    "Runtime lifecycle dispatch skipped after concurrent claim",
                    extra={
                        "runtime_id": preflight.runtime_id,
                        "agent_id": preflight.agent_id,
                        "provider_id": provider_id,
                        "desired_generation": preflight.desired_generation,
                        "command_type": command_type.value,
                    },
                )
            return False
        admission = admission_result
        runtime_configuration = admission.runtime_configuration
        created_at = datetime.now(UTC)
        runner_credential_id = self._config.runner_credential_identifier.credential_id(
            runtime_id=admission.runtime_id,
            desired_generation=admission.desired_generation,
        )
        result = await self._control_protocol.dispatch_provider_command(
            RuntimeProviderCommand(
                provider_id=provider_id,
                provider_generation=admission.connection_generation,
                runtime_id=admission.runtime_id,
                desired_generation=admission.desired_generation,
                command_type=command_type,
                reset_final_desired_state=_reset_final_desired_state(admission),
                payload={
                    "identity": {
                        "runtime_id": admission.runtime_id,
                        "agent_id": admission.agent_id,
                        "workspace_id": admission.workspace_id,
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
            await self._dispatch_repository.record_connection_outcome(
                admission,
                RuntimeProviderConnectionState.CONNECTED,
            )
            _LOGGER.info(
                "Runtime lifecycle command dispatched",
                extra={
                    "runtime_id": admission.runtime_id,
                    "agent_id": admission.agent_id,
                    "provider_id": provider_id,
                    "provider_generation": admission.connection_generation,
                    "desired_generation": admission.desired_generation,
                    "command_type": command_type.value,
                    "request_id": result.request_id,
                    "configuration_sequence": (
                        runtime_configuration.evidence.configuration_sequence
                    ),
                    "reconciliation_kind": reconciliation_kind,
                    "reconciliation_reason": reconciliation_reason,
                },
            )
            return True
        if isinstance(result, RuntimeProtocolRouteUnavailable):
            _LOGGER.warning(
                "Runtime lifecycle dispatch route unavailable",
                extra={
                    "runtime_id": admission.runtime_id,
                    "agent_id": admission.agent_id,
                    "provider_id": provider_id,
                    "desired_generation": admission.desired_generation,
                    "command_type": command_type.value,
                },
            )
            await self._dispatch_repository.record_connection_outcome(
                admission,
                RuntimeProviderConnectionState.DISCONNECTED,
            )
            return False
        if isinstance(result, RuntimeProtocolStaleGeneration):
            _LOGGER.info(
                "Runtime lifecycle dispatch skipped for stale provider generation",
                extra={
                    "runtime_id": admission.runtime_id,
                    "agent_id": admission.agent_id,
                    "provider_id": provider_id,
                    "provider_generation": admission.connection_generation,
                    "desired_generation": admission.desired_generation,
                    "command_type": command_type.value,
                },
            )
            return False
        raise AssertionError(f"unexpected dispatch result: {result!r}")


def _reset_final_desired_state(
    admission: RuntimeLifecycleDispatchAdmission,
) -> str | None:
    if admission.last_lifecycle_command != RuntimeLifecycleCommandType.RESET:
        return None
    if admission.reset_final_desired_state is None:
        return None
    return admission.reset_final_desired_state.value


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
