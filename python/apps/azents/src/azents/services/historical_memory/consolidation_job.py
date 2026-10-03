"""Independent Lightweight consolidation jobs, heartbeat and quota-only restarts."""

import asyncio
import dataclasses
import datetime
from typing import Annotated, Protocol

from fastapi import Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.historical_memory_budget import ConsolidationBudgetExceeded
from azents.core.historical_memory_consolidation import ConsolidationUnitKey
from azents.core.historical_memory_publication import ConsolidationOutputError
from azents.core.model_operation import ModelOperationChainExhaustedError
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.model_stream import (
    ModelDispatchAdmissionError,
    ModelStreamClock,
    ModelStreamWatchdog,
    get_model_stream_watchdog,
)
from azents.engine.run.errors import ModelStreamTimeoutError
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
)
from azents.engine.run.resolve import resolve_model_candidate_runtime
from azents.job_runtime.types import (
    JobExecutionContext,
    JobPayload,
    validate_job_payload,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.engine_read import EngineModelReadRepository
from azents.repos.engine_read_deps import get_engine_model_read_repository
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
)
from azents.repos.historical_memory_consolidation.budget import (
    ConsolidationBudgetRepository,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.operations import (
    ConsolidationModelOperationRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationClaim,
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.publication import (
    ConsolidationPublicationOutcome,
    ConsolidationPublicationRepository,
)
from azents.repos.historical_memory_consolidation.recovery import (
    ConsolidationRecoveryRepository,
)
from azents.repos.historical_memory_consolidation.sources import (
    ConsolidationSourceRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
)
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver
from azents.services.historical_memory.consolidation_host import (
    ConsolidationIterationHost,
)
from azents.services.historical_memory.consolidation_model import (
    ConsolidationModelCapabilityError,
    ConsolidationProviderModel,
    bind_consolidation_provider_model,
)
from azents.services.historical_memory.consolidation_tools import (
    ConsolidationToolBindings,
)
from azents.services.historical_memory.draft_vfs import ConsolidationVfsObservations
from azents.services.model_metadata import ModelMetadataService


class HistoricalMemoryConsolidationJobPayload(BaseModel):
    """Exact unit identity only; no caller-created owner authority or transcript."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    unit: ConsolidationUnitKey


class SupervisedConsolidationAttempt(Protocol):
    """Only lease supervision and lifecycle, independent of model/tool internals."""

    @property
    def claim(self) -> ConsolidationClaim: ...

    @property
    def ownership_repository(self) -> ConsolidationOwnershipRepository: ...

    @property
    def publication_repository(self) -> ConsolidationPublicationRepository: ...

    async def run(self) -> ConsolidationPublicationOutcome: ...

    async def close(self) -> None: ...


async def supervise_consolidation_attempt(
    attempt: SupervisedConsolidationAttempt,
    *,
    clock: ModelStreamClock,
) -> ConsolidationPublicationOutcome:
    """Protect setup, every candidate host and handoff under one claim deadline."""

    async def renew() -> None:
        while True:
            await clock.sleep(30)
            await attempt.ownership_repository.renew(attempt.claim.principal)

    execution = asyncio.create_task(attempt.run())
    heartbeat = asyncio.create_task(renew())
    seconds = max(
        0,
        (
            attempt.claim.deadline_at - datetime.datetime.now(datetime.UTC)
        ).total_seconds(),
    )
    terminal_error: Exception | asyncio.CancelledError | None = None
    try:
        async with asyncio.timeout(seconds):
            done, _ = await asyncio.wait(
                {execution, heartbeat}, return_when=asyncio.FIRST_COMPLETED
            )
            if execution in done:
                return execution.result()
            # Heartbeat has no successful terminal state. Prefer the authoritative
            # committed outcome if renewal raced with normal publication.
            committed = await attempt.publication_repository.inspect_outcome(
                attempt.claim.principal
            )
            if committed is not None:
                return committed
            heartbeat.result()
            raise RuntimeError("Consolidation heartbeat ended unexpectedly.")
    except asyncio.CancelledError as error:
        terminal_error = error
        raise
    except Exception as error:
        terminal_error = error
        raise
    finally:
        for task in (execution, heartbeat):
            if not task.done():
                task.cancel()
        await asyncio.gather(execution, heartbeat, return_exceptions=True)
        try:
            await attempt.close()
        except asyncio.CancelledError:
            raise
        except Exception as close_error:
            if terminal_error is not None:
                raise terminal_error from close_error
            raise


def consolidation_failure_code(error: Exception) -> str:
    """Closed safe operational labels, never prompt/provider-body persistence."""
    if isinstance(error, ModelProviderFailure):
        return error.failure_code
    if isinstance(error, ModelStreamTimeoutError):
        return error.failure_code
    if isinstance(error, ConsolidationBudgetExceeded):
        return "budget_exhausted"
    if isinstance(error, ModelDispatchAdmissionError):
        return f"dispatch_{error.reason}_rejected"
    if isinstance(error, ConsolidationOutputError):
        return "invalid_authored_output"
    if isinstance(error, ConsolidationModelCapabilityError):
        return "lightweight_capability_unavailable"
    if isinstance(error, ModelOperationChainExhaustedError):
        return "lightweight_chain_exhausted"
    if isinstance(error, ConsolidationAuthorityError):
        return "authority_unconfirmed"
    if isinstance(error, TimeoutError):
        return "attempt_deadline"
    return "internal_execution_failed"


@dataclasses.dataclass
class HistoricalMemoryConsolidationService:
    """Own short repository operations and RAM hosts without a foreground Session."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    config: Annotated[Config, Depends(get_config)]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    health_repository: Annotated[
        ModelCandidateHealthRepository, Depends(ModelCandidateHealthRepository)
    ]
    model_read_repository: Annotated[
        EngineModelReadRepository,
        Depends(get_engine_model_read_repository),
    ]
    metadata_service: Annotated[ModelMetadataService, Depends(ModelMetadataService)]
    runtime_token_resolver: Annotated[
        EngineRuntimeTokenResolver, Depends(EngineRuntimeTokenResolver)
    ]
    sdk_factories: Annotated[ModelSDKFactories, Depends(get_model_sdk_factories)]
    watchdog: Annotated[ModelStreamWatchdog, Depends(get_model_stream_watchdog)]

    async def run_unit(
        self, key: ConsolidationUnitKey
    ) -> ConsolidationPublicationOutcome | None:
        ownership = ConsolidationOwnershipRepository(self.session_manager)
        claim = await ownership.claim(key)
        if claim is None:
            return None
        attempt = ConsolidationAttemptExecution(
            self,
            claim,
            ownership,
            ConsolidationPublicationRepository(self.session_manager),
        )
        try:
            return await supervise_consolidation_attempt(
                attempt, clock=self.watchdog.clock
            )
        except asyncio.CancelledError:
            # Expiry/new-owner recovery remains authoritative on shutdown.
            raise
        except Exception as error:
            try:
                await ownership.fail(
                    claim.principal,
                    failure_code=consolidation_failure_code(error),
                    cancelled=False,
                )
            except ConsolidationAuthorityError:
                # A revoked/expired owner cannot write terminal metadata. Its
                # original failure still propagates to Job Runtime unchanged.
                raise error from None
            raise


@dataclasses.dataclass
class ConsolidationAttemptExecution:
    """Claim-scoped preparation and quota handoff around the shared iteration core."""

    service: HistoricalMemoryConsolidationService
    claim: ConsolidationClaim
    ownership_repository: ConsolidationOwnershipRepository
    publication_repository: ConsolidationPublicationRepository
    active_host: ConsolidationIterationHost | None = dataclasses.field(
        init=False, default=None
    )
    active_model: ConsolidationProviderModel | None = dataclasses.field(
        init=False, default=None
    )

    async def run(self) -> ConsolidationPublicationOutcome:
        service = self.service
        key = self.claim.principal.unit
        operations = ConsolidationModelOperationRepository(
            service.session_manager, service.agent_repository, service.health_repository
        )
        recovery = ConsolidationRecoveryRepository(service.session_manager)
        while True:
            self.active_host = None
            self.active_model = None
            await recovery.prepare(self.claim.principal)
            await ConsolidationWorkRepository(
                service.session_manager
            ).retire_obsolete_pending(self.claim.principal)
            operation = await operations.begin(self.claim.principal)
            candidate = operation.current_candidate
            runtime = await resolve_model_candidate_runtime(
                agent_id=key.agent_id,
                workspace_id=key.workspace_id,
                selection=candidate.model_selection,
                settings=candidate.settings,
                context_source=None,
                model_read_repository=service.model_read_repository,
                runtime_token_resolver=service.runtime_token_resolver,
                model_metadata_service=service.metadata_service,
            )
            if runtime.failure:
                raise ConsolidationModelCapabilityError(
                    "Consolidation Lightweight route is unavailable."
                )
            resolved = runtime.value
            model = bind_consolidation_provider_model(
                selection=candidate.model_selection,
                settings=candidate.settings,
                credential_kwargs=resolved.credential_kwargs,
                effective_input_tokens=resolved.effective_input_tokens,
                sdk_factories=service.sdk_factories,
                watchdog=service.watchdog,
                websocket_enabled=service.config.openai_responses_websocket_enabled,
            )
            self.active_model = model
            work = ConsolidationWorkRepository(service.session_manager)
            bindings = ConsolidationToolBindings(
                ConsolidationVfsObservations(self.claim.principal),
                ConsolidationDraftRepository(service.session_manager),
                ConsolidationSourceRepository(service.session_manager),
                work,
                self.ownership_repository,
            )
            self.active_host = ConsolidationIterationHost(
                self.claim,
                model,
                bindings,
                ConsolidationBudgetRepository(service.session_manager),
                self.ownership_repository,
                work,
                self.publication_repository,
            )
            try:
                return await self.active_host.run()
            except asyncio.CancelledError:
                raise
            except ModelProviderFailure as failure:
                if (
                    failure.category
                    is not ModelProviderFailureCategory.QUOTA_OR_BILLING
                ):
                    raise
                advanced = await operations.advance_after_quota(
                    self.claim.principal, failure=failure
                )
                if advanced is None:
                    raise
                # Heartbeat/deadline remain active through this handoff. The shared
                # core closed the old RAM history and SDK before fresh recovery.

    async def close(self) -> None:
        if self.active_host is not None:
            await self.active_host.close()
        elif self.active_model is not None:
            await self.active_model.close()
        self.active_host = None
        self.active_model = None


async def execute_historical_memory_consolidation_job(
    context: JobExecutionContext,
) -> JobPayload:
    from azents.services.historical_memory.consolidation_discovery import (  # noqa: PLC0415
        HistoricalMemoryConsolidationDiscoveryService,
    )

    payload = HistoricalMemoryConsolidationJobPayload.model_validate(
        context.request.payload
    )
    service = await context.container.solve(HistoricalMemoryConsolidationService)
    result = await service.run_unit(payload.unit)
    if result is not None:
        discovery = await context.container.solve(
            HistoricalMemoryConsolidationDiscoveryService
        )
        await discovery.dispatch_pending(agent_id=payload.unit.agent_id)
    return validate_job_payload(
        {
            "published_revision_id": None if result is None else result.revision_id,
            "coalesced": result is None,
        }
    )
