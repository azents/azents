"""Agent Runtime desired-state reconciliation."""

import dataclasses
import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

from azents_runtime_control.provider import (
    RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_POLICY,
    RuntimeProviderReport,
)
from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as RuntimeProviderCommandType,
)
from azents_runtime_control.provider import (
    RuntimeProviderReconciliationStatus as SharedProviderReconciliationStatus,
)
from azents_runtime_control.runtime_configuration import (
    RuntimeConfigurationEnvelope,
    RuntimeConfigurationEvidence,
    canonical_runtime_configuration_json,
    parse_runtime_configuration_envelope,
)
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
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
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeFailurePatch
from azents.repos.runtime_profile.data import RuntimeConfigurationState
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
        coordination_store: RuntimeCoordinationStore,
        control_protocol: RuntimeControlProtocolService,
        config: RuntimeLifecycleDispatchConfig,
    ) -> None:
        """Initialize the reconciler."""
        self._agent_repository = agent_repository
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
        """Immediately repair one current NetworkPolicy drift observation.

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
            observation.kind != RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_POLICY
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
            "Runtime NetworkPolicy drift repair handed off",
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
        locked_session: AsyncSession | None = None,
    ) -> bool:
        if locked_session is None:
            async with self._session_manager() as session:
                agent = await self._agent_repository.lock_by_id(
                    session,
                    runtime.agent_id,
                )
                if agent is None or not _runtime_dispatch_allowed(
                    agent.runtime_capability,
                    command_type,
                ):
                    return False
                current = await self._runtime_repository.get_by_id_for_update(
                    session,
                    runtime.id,
                )
                if not _runtime_dispatch_snapshot_matches(current, runtime):
                    return False
                assert current is not None
                return await self._dispatch_runtime_command(
                    current,
                    command_type=command_type,
                    claim_lifecycle=claim_lifecycle,
                    required_provider_generation=required_provider_generation,
                    required_observed_generation=required_observed_generation,
                    required_configuration_sequence=(required_configuration_sequence),
                    reconciliation_kind=reconciliation_kind,
                    reconciliation_reason=reconciliation_reason,
                    locked_session=session,
                )
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
                locked_session=locked_session,
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
            if locked_session is None:
                async with self._session_manager() as session:
                    await self._runtime_repository.record_provider_connection_state(
                        session,
                        runtime.id,
                        RuntimeProviderConnectionState.DISCONNECTED,
                    )
            else:
                await self._runtime_repository.record_provider_connection_state(
                    locked_session,
                    runtime.id,
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
                    "runtime_id": runtime.id,
                    "agent_id": runtime.agent_id,
                    "provider_id": provider_id,
                    "required_provider_generation": required_provider_generation,
                    "connection_provider_generation": connection.generation,
                    "desired_generation": runtime.desired_generation,
                    "command_type": command_type.value,
                },
            )
            return False
        if (
            required_observed_generation is not None
            or required_configuration_sequence is not None
        ):
            if locked_session is None:
                async with self._session_manager() as session:
                    current = await self._runtime_repository.get_by_id(
                        session, runtime.id
                    )
                    state = await self._profile_repository.get_configuration_state(
                        session,
                        runtime_id=runtime.id,
                    )
            else:
                current = runtime
                state = await self._profile_repository.get_configuration_state(
                    locked_session,
                    runtime_id=runtime.id,
                )
            if not _current_network_policy_repair_target(
                current,
                state=state,
                provider_id=provider_id,
                provider_generation=required_provider_generation,
                observed_generation=required_observed_generation,
                configuration_sequence=required_configuration_sequence,
            ):
                return False
            assert current is not None
            runtime = current

        if claim_lifecycle:
            claimed = await self._runtime_repository.claim_lifecycle_dispatch(
                locked_session,
                runtime.id,
                runtime.desired_generation,
                retry_delay=self._config.lifecycle_retry_delay,
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
                locked_session=locked_session,
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
                locked_session=locked_session,
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
            if locked_session is None:
                async with self._session_manager() as session:
                    await self._runtime_repository.record_provider_connection_state(
                        session,
                        runtime.id,
                        RuntimeProviderConnectionState.CONNECTED,
                    )
            else:
                await self._runtime_repository.record_provider_connection_state(
                    locked_session,
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
                    "runtime_id": runtime.id,
                    "agent_id": runtime.agent_id,
                    "provider_id": provider_id,
                    "desired_generation": runtime.desired_generation,
                    "command_type": command_type.value,
                },
            )
            if locked_session is None:
                async with self._session_manager() as session:
                    await self._runtime_repository.record_provider_connection_state(
                        session,
                        runtime.id,
                        RuntimeProviderConnectionState.DISCONNECTED,
                    )
            else:
                await self._runtime_repository.record_provider_connection_state(
                    locked_session,
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
        locked_session: AsyncSession | None,
        require_ready: bool = True,
    ) -> RuntimeConfigurationEnvelope:
        if locked_session is None:
            async with self._session_manager() as session:
                state = await self._profile_repository.get_configuration_state(
                    session,
                    runtime_id=runtime.id,
                )
        else:
            state = await self._profile_repository.get_configuration_state(
                locked_session,
                runtime_id=runtime.id,
            )
        if state is None:
            raise ValueError("Runtime configuration state is missing.")
        desired = state.desired
        slot = (
            desired
            if desired.status is RuntimeConfigurationStateStatus.READY
            else state.applied
        )
        if require_ready:
            slot = desired
        if (
            slot is None
            or slot.document is None
            or slot.digest is None
            or slot.document.resolved_configuration is None
        ):
            raise ValueError("Runtime configuration target document is missing.")
        document = slot.document
        resolved_configuration = document.resolved_configuration
        assert resolved_configuration is not None
        if (
            runtime.runtime_provider_resource_id is None
            or document.provider_id != runtime.runtime_provider_resource_id
        ):
            raise ValueError("Runtime configuration Provider binding is invalid.")
        if require_ready and slot.target_generation != runtime.desired_generation:
            raise ValueError("Runtime configuration target generation is stale.")
        envelope = RuntimeConfigurationEnvelope(
            evidence=RuntimeConfigurationEvidence(
                configuration_sequence=slot.sequence,
                digest=slot.digest,
                desired_generation=runtime.desired_generation,
            ),
            resolved_configuration_json=canonical_runtime_configuration_json(
                resolved_configuration
            ),
        )
        configuration = parse_runtime_configuration_envelope(
            envelope,
            desired_generation=runtime.desired_generation,
            expected_provider_kind=None,
        )
        if (
            configuration.provider.id != document.provider_id
            or configuration.provider.logical_id != runtime.runtime_provider_id
            or configuration.provider.capability_revision_id
            != document.provider_capability_revision_id
        ):
            raise ValueError("Runtime configuration Provider reference is invalid.")
        if not require_ready:
            return envelope
        if (
            configuration.infrastructure_profile.id
            != document.infrastructure_profile_id
            or configuration.infrastructure_profile.version
            != document.infrastructure_profile_version
        ):
            raise ValueError(
                "Runtime configuration Infrastructure Profile reference is invalid."
            )
        if (
            configuration.workspace_runtime_profile.id
            != document.workspace_runtime_profile_id
            or configuration.workspace_runtime_profile.version
            != document.workspace_runtime_profile_version
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
        locked_session: AsyncSession | None = None,
    ) -> None:
        if locked_session is None:
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
            return
        await self._runtime_repository.record_runtime_failure(
            locked_session,
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


def _runtime_dispatch_allowed(
    capability: AgentRuntimeCapability,
    command_type: RuntimeProviderCommandType,
) -> bool:
    """Allow ordinary dispatch only while managed; removal owns terminal delete."""
    return capability is AgentRuntimeCapability.MANAGED or (
        capability is AgentRuntimeCapability.REMOVING
        and command_type is RuntimeProviderCommandType.TERMINAL_DELETE
    )


def _runtime_dispatch_snapshot_matches(
    current: AgentRuntime | None,
    expected: AgentRuntime,
) -> bool:
    """Require the locked Runtime to match the selected dispatch authority."""
    return (
        current is not None
        and current.agent_id == expected.agent_id
        and current.runtime_provider_id == expected.runtime_provider_id
        and current.runtime_provider_resource_id
        == expected.runtime_provider_resource_id
        and current.desired_state is expected.desired_state
        and current.desired_generation == expected.desired_generation
        and current.last_lifecycle_command is expected.last_lifecycle_command
        and current.terminal_delete_requested_generation
        == expected.terminal_delete_requested_generation
        and current.configuration_sequence == expected.configuration_sequence
        and current.provider_generation == expected.provider_generation
        and current.provider_observed_generation
        == expected.provider_observed_generation
        and current.provider_observed_state is expected.provider_observed_state
    )


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


def _current_network_policy_repair_target(
    runtime: AgentRuntime | None,
    *,
    state: RuntimeConfigurationState | None,
    provider_id: str,
    provider_generation: int | None,
    observed_generation: int | None,
    configuration_sequence: int | None,
) -> bool:
    """Return whether one drift-repair snapshot remains current at dispatch."""
    return (
        runtime is not None
        and runtime.runtime_provider_id == provider_id
        and runtime.desired_state is RuntimeDesiredState.RUNNING
        and runtime.provider_observed_state is RuntimeProviderObservedState.RUNNING
        and runtime.provider_generation == provider_generation
        and runtime.provider_observed_generation == observed_generation
        and runtime.desired_generation == observed_generation
        and runtime.last_lifecycle_dispatch_generation >= runtime.desired_generation
        and runtime.terminal_delete_requested_generation is None
        and state is not None
        and state.applied is not None
        and state.desired.status is RuntimeConfigurationStateStatus.READY
        and state.desired.sequence == configuration_sequence
        and state.applied.sequence == configuration_sequence
    )
