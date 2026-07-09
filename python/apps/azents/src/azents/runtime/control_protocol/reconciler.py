"""Agent Runtime desired-state reconciliation."""

import dataclasses
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeFailurePatch
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


@dataclasses.dataclass(frozen=True)
class RuntimeLifecycleDispatchConfig:
    """Config required to dispatch lifecycle commands to Providers."""

    runner_image: str
    runner_control_endpoint: str
    runner_control_auth_token: str | None
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
        session_manager: SessionManager[AsyncSession],
        coordination_store: RuntimeCoordinationStore,
        control_protocol: RuntimeControlProtocolService,
        config: RuntimeLifecycleDispatchConfig,
    ) -> None:
        """Initialize the reconciler."""
        self._runtime_repository = runtime_repository
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
            observe_runtimes = (
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
        for runtime in observe_runtimes:
            if runtime.id in lifecycle_runtime_ids:
                continue
            if await self._dispatch_observe(runtime):
                dispatched += 1
        return dispatched

    async def _dispatch_runtime(self, runtime: AgentRuntime) -> bool:
        return await self._dispatch_runtime_command(
            runtime,
            command_type=runtime.last_lifecycle_command,
            claim_lifecycle=True,
        )

    async def _dispatch_observe(self, runtime: AgentRuntime) -> bool:
        return await self._dispatch_runtime_command(
            runtime,
            command_type=RuntimeLifecycleCommandType.OBSERVE,
            claim_lifecycle=False,
        )

    async def _dispatch_runtime_command(
        self,
        runtime: AgentRuntime,
        *,
        command_type: RuntimeLifecycleCommandType | None,
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
        if command_type is None:
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
                        "runner_auth_token": _runner_auth_credential_id(runtime),
                        "control_token": self._config.runner_control_auth_token,
                    },
                },
                deadline_at=created_at + self._config.provider_command_deadline,
            ),
            created_at=created_at,
        )
        if isinstance(result, RuntimeDispatchResult):
            async with self._session_manager() as session:
                if claim_lifecycle:
                    await self._runtime_repository.record_provider_connection_state(
                        session,
                        runtime.id,
                        RuntimeProviderConnectionState.CONNECTED,
                    )
                else:
                    await self._runtime_repository.mark_provider_observe_dispatched(
                        session,
                        runtime.id,
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


def _runner_auth_credential_id(runtime: AgentRuntime) -> str:
    return f"runtime-runner:{runtime.id}:{runtime.desired_generation}"
