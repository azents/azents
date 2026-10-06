"""Private Memory execution dispatched by the common Session Worker."""

import asyncio
import dataclasses
import datetime
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated

from fastapi import Depends

from azents.broker.types import SessionWakeUp
from azents.core.agent import AgentModelSelection, SelectableModelCandidate
from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import AgentRunStatus
from azents.core.historical_memory_consolidation import (
    MemoryAcceptedOutcome,
    MemoryExecutionAuthorityError,
    MemoryExecutionBinding,
    MemoryExecutionPrincipal,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.context.compaction import SummaryModelCall
from azents.engine.events.model_messages import TransientModelMessage
from azents.engine.events.protocols import NormalizedAdapterOutput
from azents.engine.events.tools import ToolCatalog
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.model_stream import (
    ModelDispatchAdmissionError,
    ModelStreamCallContext,
    ModelStreamWatchdog,
    get_model_stream_watchdog,
)
from azents.engine.provider_model_operation import (
    PreparedModelOperation,
    ProviderModelOperation,
    bind_provider_model_operation,
    call_model_operation_text_with_usage,
)
from azents.engine.run.model_transport import (
    InMemoryModelTransportState,
    ModelTransportState,
)
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
)
from azents.engine.run.resolve import resolve_model_candidate_runtime
from azents.engine.run.task_supervision import (
    EXPLICIT_STOP_POLL_INTERVAL,
    SESSION_OWNER_HEARTBEAT_INTERVAL,
    SHUTDOWN_COMPLETION_TIMEOUT,
    ExecutionTaskSupervision,
)
from azents.engine.run.types import SHUTDOWN_CANCEL_MESSAGE, USER_STOP_CANCEL_MESSAGE
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.engine_read import EngineModelReadRepository
from azents.repos.engine_read_deps import get_engine_model_read_repository
from azents.repos.historical_memory_consolidation.execution import (
    MemoryExecutionRepository,
)
from azents.repos.historical_memory_consolidation.operations import (
    ConsolidationModelOperationRepository,
)
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.session_archive_operations import SessionArchiveOperations
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_execution_file import SessionExecutionFileRepository
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver
from azents.services.historical_memory.consolidation_host import (
    ConsolidationIterationHost,
)
from azents.services.historical_memory.consolidation_model import (
    ConsolidationModelCapabilityError,
)
from azents.services.historical_memory.consolidation_tools import (
    ConsolidationToolBindings,
)
from azents.services.historical_memory.execution_context import (
    MemoryExecutionContextService,
)
from azents.services.model_metadata import ModelMetadataService
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.supervisor import RunStopController

logger = logging.getLogger(__name__)


def get_memory_model_operations(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
    agents: Annotated[AgentRepository, Depends(AgentRepository)],
    health: Annotated[
        ModelCandidateHealthRepository, Depends(ModelCandidateHealthRepository)
    ],
    capabilities: Annotated[
        ActiveModelCapabilitiesRepository, Depends(ActiveModelCapabilitiesRepository)
    ],
    executions: Annotated[
        MemoryExecutionRepository, Depends(MemoryExecutionRepository)
    ],
    runs: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
) -> ConsolidationModelOperationRepository:
    """Compose common candidate operations without a public Session repository."""
    return ConsolidationModelOperationRepository(
        session_manager, agents, health, capabilities, executions, runs
    )


@dataclasses.dataclass(frozen=True)
class _MemorySummaryCall:
    """Use the common physical summary contract with the actual captured owner."""

    principal: MemoryExecutionPrincipal
    candidate: SelectableModelCandidate
    credentials: dict[str, object]
    effective_input_tokens: int
    sdk_factories: ModelSDKFactories
    watchdog: ModelStreamWatchdog
    websocket_enabled: bool
    context_port: MemoryExecutionContextService
    executions: MemoryExecutionRepository
    check_stop: Callable[[], Awaitable[bool]]

    async def __call__(
        self,
        *,
        candidate: SelectableModelCandidate,
        credential_kwargs: dict[str, object],
        effective_input_tokens: int,
        transport_state: ModelTransportState,
        system_prompt: str,
        user_prompt: str,
        conversation_text: str,
        session_id: str | None = None,
    ) -> str:
        if (
            candidate != self.candidate
            or credential_kwargs != self.credentials
            or effective_input_tokens != self.effective_input_tokens
            or session_id != self.principal.owner.session_id
        ):
            raise ValueError(
                "Compaction model does not match the captured Memory route."
            )
        if await self.check_stop():
            raise asyncio.CancelledError(USER_STOP_CANCEL_MESSAGE)
        await self.executions.authorize_execution(self.principal)
        selection = candidate.model_selection

        async def check_admitted_stop() -> bool:
            try:
                if await self.check_stop():
                    return True
                await self.executions.authorize_execution(self.principal)
            except (
                CanonicalExecutionOwnerGenerationStaleError,
                MemoryExecutionAuthorityError,
            ) as error:
                raise ModelDispatchAdmissionError("ownership") from error
            return False

        result = await call_model_operation_text_with_usage(
            selection=selection,
            settings=candidate.settings,
            credential_kwargs=credential_kwargs,
            effective_input_tokens=effective_input_tokens,
            sdk_factories=self.sdk_factories,
            watchdog=self.watchdog,
            websocket_enabled=self.websocket_enabled,
            instructions=system_prompt,
            input_text=user_prompt + conversation_text,
            call_context=ModelStreamCallContext(
                call_kind="compaction",
                provider=selection.provider.value,
                provider_integration_id=selection.llm_provider_integration_id,
                model=selection.model_identifier,
                session_id=self.principal.owner.session_id,
                run_id=self.principal.run_id,
                attempt_number=None,
                check_stop=check_admitted_stop,
            ),
            transport_state=transport_state,
        )
        await self.context_port.record_usage(self.principal, result.usage)
        return result.text


@dataclasses.dataclass(frozen=True)
class MemoryProviderModel:
    """Captured provider operation plus the common context summary callback."""

    operation: ProviderModelOperation
    candidate: SelectableModelCandidate
    credential_kwargs: dict[str, object]
    transport_state: ModelTransportState
    summary_call: SummaryModelCall

    @property
    def selection(self) -> AgentModelSelection:
        return self.operation.selection

    @property
    def effective_input_tokens(self) -> int:
        return self.operation.effective_input_tokens

    @property
    def max_output_tokens(self) -> int | None:
        return self.operation.max_output_tokens

    def prepare(
        self,
        messages: Sequence[TransientModelMessage],
        catalog: ToolCatalog | None,
        *,
        system_prompt: str,
        output_tokens: int | None,
    ) -> PreparedModelOperation:
        return self.operation.prepare(
            messages, catalog, system_prompt=system_prompt, output_tokens=output_tokens
        )

    async def invoke(
        self,
        prepared: PreparedModelOperation,
        *,
        context: ModelStreamCallContext,
    ) -> NormalizedAdapterOutput[TransientModelMessage]:
        return await self.operation.invoke(prepared, context=context)

    async def close(self) -> None:
        await self.operation.close()


@dataclasses.dataclass(frozen=True)
class MemoryRunExecutor:
    """Run a bound private purpose through the existing Worker owner and supervision."""

    executions: Annotated[MemoryExecutionRepository, Depends(MemoryExecutionRepository)]
    files: Annotated[
        SessionExecutionFileRepository, Depends(SessionExecutionFileRepository)
    ]
    context_port: Annotated[
        MemoryExecutionContextService, Depends(MemoryExecutionContextService)
    ]
    models: Annotated[
        ConsolidationModelOperationRepository, Depends(get_memory_model_operations)
    ]
    model_read_repository: Annotated[
        EngineModelReadRepository, Depends(get_engine_model_read_repository)
    ]
    runtime_token_resolver: Annotated[
        EngineRuntimeTokenResolver, Depends(EngineRuntimeTokenResolver)
    ]
    metadata_service: Annotated[ModelMetadataService, Depends(ModelMetadataService)]
    sdk_factories: Annotated[ModelSDKFactories, Depends(get_model_sdk_factories)]
    watchdog: Annotated[ModelStreamWatchdog, Depends(get_model_stream_watchdog)]
    config: Annotated[Config, Depends(get_config)]
    lifecycle: Annotated[SessionLifecycleService, Depends(SessionLifecycleService)]
    archives: Annotated[SessionArchiveOperations, Depends(SessionArchiveOperations)]

    async def execute(
        self,
        binding: MemoryExecutionBinding,
        *,
        owner_generation: int,
        shutdown_event: asyncio.Event,
        stop_controller: RunStopController,
        check_stop: Callable[[], Awaitable[bool]],
        drain_stop_signals: Callable[[], None],
    ) -> RunExecutionResult:
        """Supervise one common Run with its admitted lifetime and turn policy."""
        principal = await self.executions.open_run(
            binding, SessionExecutionOwner(binding.session_id, owner_generation)
        )
        engine_task = asyncio.create_task(
            self._run_domain(
                principal, check_stop=check_stop, stop_controller=stop_controller
            )
        )
        stop_controller.register_active_task(engine_task)
        accepted_during_stop: MemoryAcceptedOutcome | None = None

        async def wait_for_stop() -> None:
            while True:
                drain_stop_signals()
                if await self.lifecycle.has_stop_request(binding.session_id):
                    stop_controller.request_user_stop()
                if stop_controller.user_stop_requested:
                    return
                await asyncio.sleep(EXPLICIT_STOP_POLL_INTERVAL)

        async def finalize_stop() -> None:
            nonlocal accepted_during_stop
            accepted_during_stop = await self.executions.finish_unaccepted(
                principal, status=AgentRunStatus.CANCELLED
            )

        def cancelled_result(terminal: bool) -> RunExecutionResult:
            return RunExecutionResult(
                toolkits=[],
                terminal_event_observed=terminal,
                no_actionable_work=False,
                run_id=principal.run_id,
                terminal_run_status=AgentRunStatus.CANCELLED if terminal else None,
            )

        supervisor = ExecutionTaskSupervision(
            session_id=binding.session_id,
            shutdown_event=shutdown_event,
            wait_for_explicit_stop=wait_for_stop,
            finalize_explicit_stop=finalize_stop,
            user_stop_requested=lambda: stop_controller.user_stop_requested,
            request_handover_stop=stop_controller.request_handover_stop,
            close_tool_admission=stop_controller.tool_admission_barrier.close,
            cancelled_result=cancelled_result,
            shutdown_timeout=SHUTDOWN_COMPLETION_TIMEOUT,
            user_stop_cancel_message=USER_STOP_CANCEL_MESSAGE,
            shutdown_cancel_message=SHUTDOWN_CANCEL_MESSAGE,
        )
        try:
            result = await supervisor.run(engine_task)
            if accepted_during_stop is not None:
                result = self._accepted_result(principal, accepted_during_stop)
            elif result.terminal_run_status is not AgentRunStatus.COMPLETED:
                latest = await self.executions.load_binding(binding.session_id)
                if latest is not None and latest.accepted is not None:
                    result = self._accepted_result(principal, latest.accepted)
            if (
                result.terminal_event_observed
                and result.terminal_run_status is not AgentRunStatus.FAILED
            ):
                await self._archive_follow_up(principal)
            return result
        finally:
            stop_controller.clear_active_task(engine_task)

    @staticmethod
    def _accepted_result(
        principal: MemoryExecutionPrincipal, outcome: MemoryAcceptedOutcome
    ) -> RunExecutionResult:
        return RunExecutionResult(
            toolkits=[],
            terminal_event_observed=True,
            no_actionable_work=False,
            run_id=principal.run_id,
            terminal_run_status=AgentRunStatus.COMPLETED,
        )

    async def _run_domain(
        self,
        principal: MemoryExecutionPrincipal,
        *,
        check_stop: Callable[[], Awaitable[bool]],
        stop_controller: RunStopController,
    ) -> RunExecutionResult:
        replacement: MemoryExecutionBinding | None = None

        async def engine() -> RunExecutionResult:
            nonlocal replacement
            seconds = max(
                0.0,
                (
                    principal.binding.deadline_at - datetime.datetime.now(datetime.UTC)
                ).total_seconds(),
            )
            async with asyncio.timeout(seconds):
                for predecessor in await self.models.archivable_predecessors(
                    principal.binding
                ):
                    await self._archive_owner(predecessor)
                await self.executions.provision_inputs(principal)
                current = await self.executions.load_binding(principal.owner.session_id)
                if current is None:
                    raise ValueError("Memory execution binding is unavailable.")
                principal_for_host = dataclasses.replace(principal, binding=current)
                host = await self._create_host(
                    principal_for_host, check_stop=check_stop
                )
                try:
                    outcome = await host.run()
                    return self._accepted_result(principal, outcome)
                except ModelProviderFailure as failure:
                    if (
                        failure.category
                        is not ModelProviderFailureCategory.QUOTA_OR_BILLING
                    ):
                        raise
                    replacement = await self.models.replace_after_quota(
                        host.principal, failure=failure
                    )
                    if replacement is None:
                        raise
                    return RunExecutionResult(
                        toolkits=[],
                        terminal_event_observed=True,
                        no_actionable_work=False,
                        run_id=principal.run_id,
                        terminal_run_status=AgentRunStatus.FAILED,
                    )

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(SESSION_OWNER_HEARTBEAT_INTERVAL)
                await self.lifecycle.heartbeat_session(
                    principal.owner.session_id,
                    owner_generation=principal.owner.owner_generation,
                )
                await self.lifecycle.renew_session_owner_heartbeat(
                    principal.owner.session_id
                )

        task = asyncio.create_task(engine())
        renewal = asyncio.create_task(heartbeat())
        try:
            done, _ = await asyncio.wait(
                {task, renewal}, return_when=asyncio.FIRST_COMPLETED
            )
            if task in done:
                result = task.result()
            else:
                renewal.result()
                raise RuntimeError("Common Session heartbeat ended unexpectedly.")
        except asyncio.CancelledError:
            latest = await self.executions.load_binding(principal.owner.session_id)
            if latest is not None and latest.accepted is not None:
                return self._accepted_result(principal, latest.accepted)
            if not (
                stop_controller.handover_stop_requested
                and not stop_controller.user_stop_requested
            ):
                await self.executions.finish_unaccepted(
                    principal, status=AgentRunStatus.CANCELLED
                )
            raise
        except Exception:
            latest = await self.executions.load_binding(principal.owner.session_id)
            if latest is not None and latest.accepted is not None:
                return self._accepted_result(principal, latest.accepted)
            await self.executions.finish_unaccepted(
                principal, status=AgentRunStatus.FAILED
            )
            raise
        finally:
            for active in (task, renewal):
                if not active.done():
                    active.cancel()
            await asyncio.gather(task, renewal, return_exceptions=True)
        if replacement is not None:
            for predecessor in await self.models.archivable_predecessors(replacement):
                await self._archive_owner(predecessor)
            try:
                await self.lifecycle.send_session_wake_up(
                    SessionWakeUp(session_id=replacement.session_id)
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Memory candidate wake-up follow-up failed",
                    extra={
                        "session_id": replacement.session_id,
                        "predecessor_session_id": principal.owner.session_id,
                    },
                )
        return result

    async def _create_host(
        self,
        principal: MemoryExecutionPrincipal,
        *,
        check_stop: Callable[[], Awaitable[bool]],
    ) -> ConsolidationIterationHost:
        operation = await self.models.begin(principal)
        selected = operation.current_candidate
        candidate = SelectableModelCandidate(
            model_selection=selected.model_selection, settings=selected.settings
        )
        runtime = await resolve_model_candidate_runtime(
            agent_id=principal.binding.unit.agent_id,
            workspace_id=principal.binding.unit.workspace_id,
            selection=candidate.model_selection,
            settings=candidate.settings,
            context_source=None,
            model_read_repository=self.model_read_repository,
            runtime_token_resolver=self.runtime_token_resolver,
            model_metadata_service=self.metadata_service,
        )
        if runtime.failure:
            raise ConsolidationModelCapabilityError(
                "Memory Lightweight route is unavailable."
            )
        resolved = runtime.value
        transport = InMemoryModelTransportState(
            websocket_enabled=self.config.openai_responses_websocket_enabled
        )
        provider = bind_provider_model_operation(
            selection=candidate.model_selection,
            settings=candidate.settings,
            credential_kwargs=resolved.credential_kwargs,
            effective_input_tokens=resolved.effective_input_tokens,
            sdk_factories=self.sdk_factories,
            watchdog=self.watchdog,
            websocket_enabled=self.config.openai_responses_websocket_enabled,
            transport_state=transport,
        )

        model = MemoryProviderModel(
            provider,
            candidate,
            resolved.credential_kwargs,
            transport,
            _MemorySummaryCall(
                principal,
                candidate,
                resolved.credential_kwargs,
                resolved.effective_input_tokens,
                self.sdk_factories,
                self.watchdog,
                self.config.openai_responses_websocket_enabled,
                self.context_port,
                self.executions,
                check_stop,
            ),
        )
        return ConsolidationIterationHost(
            principal,
            model,
            ConsolidationToolBindings(principal, self.files, self.executions),
            self.executions,
            self.context_port,
            check_stop,
        )

    async def _archive_follow_up(self, principal: MemoryExecutionPrincipal) -> None:
        await self._archive_owner(principal.owner)

    async def archive_previous(
        self, binding: MemoryExecutionBinding, *, owner_generation: int
    ) -> None:
        """Retry settled predecessor archival without creating model work."""
        await self._archive_owner(
            SessionExecutionOwner(binding.session_id, owner_generation)
        )

    async def _archive_owner(self, owner: SessionExecutionOwner) -> None:
        try:
            target = await self.archives.archive(
                root_session_id=owner.session_id,
                expected_owner_generation=owner.owner_generation,
            )
            if target is not None and target.cleanup_plans:
                raise RuntimeError(
                    "Private Memory execution has unexpected resource effects."
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Memory execution archive follow-up failed",
                extra={
                    "session_id": owner.session_id,
                },
            )
