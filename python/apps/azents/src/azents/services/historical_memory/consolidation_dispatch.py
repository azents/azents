"""RAM-only logical-call binding to durable physical-request admission and usage."""

import dataclasses

from uuid6 import uuid7

from azents.core.historical_memory_budget import (
    ConsolidationBudgetExceeded,
    ConsolidationDispatchReservation,
    ConsolidationUsage,
)
from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.engine.events.types import TokenUsagePayload
from azents.engine.model_stream import (
    InternalModelCallIdentity,
    InternalModelStreamCallContext,
    ModelDispatchAdmissionError,
)
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
)
from azents.repos.historical_memory_consolidation.budget import (
    ConsolidationBudgetRepository,
)


def scalar_consolidation_usage(
    usage: TokenUsagePayload | None,
) -> ConsolidationUsage | None:
    """Drop raw payloads while preserving normalized cost and estimator provenance."""
    if usage is None:
        return None
    provenance = usage.cost_provenance
    return ConsolidationUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        cached_tokens=usage.cached_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        cost_usd=usage.cost_usd,
        cost_method=None if provenance is None else provenance.method,
        cost_source_snapshot_id=None
        if provenance is None
        else provenance.source_snapshot_id,
        cost_source_hash=None if provenance is None else provenance.source_hash,
        cost_source_model_key=None
        if provenance is None
        else provenance.source_model_key,
        cost_estimator_version=None
        if provenance is None
        else provenance.estimator_version,
    )


@dataclasses.dataclass
class ConsolidationDispatchAdmission:
    """Every callback creates a fresh reservation; no transaction spans SDK I/O."""

    principal: ConsolidationJobPrincipal
    repository: ConsolidationBudgetRepository
    input_tokens: int
    output_tokens: int
    reservations: list[ConsolidationDispatchReservation] = dataclasses.field(
        init=False, default_factory=list
    )
    settled: bool = dataclasses.field(init=False, default=False)

    async def admit(self) -> None:
        if self.settled:
            raise ModelDispatchAdmissionError("policy")
        try:
            reservation = await self.repository.reserve_model(
                self.principal,
                dispatch_id=uuid7().hex,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
            )
        except ConsolidationBudgetExceeded as error:
            raise ModelDispatchAdmissionError("budget") from error
        except ConsolidationAuthorityError as error:
            raise ModelDispatchAdmissionError("ownership") from error
        self.reservations.append(reservation)

    def context(
        self,
        *,
        unit_id: str,
        provider: str,
        integration_id: str,
        model: str,
    ) -> InternalModelStreamCallContext:
        return InternalModelStreamCallContext(
            call_kind="historical_memory",
            provider=provider,
            provider_integration_id=integration_id,
            model=model,
            session_id=None,
            run_id=None,
            attempt_number=1,
            check_stop=None,
            identity=InternalModelCallIdentity(
                agent_id=self.principal.unit.agent_id,
                workspace_id=self.principal.unit.workspace_id,
                unit_id=unit_id,
                attempt_id=self.principal.attempt_id,
            ),
            admit_dispatch=self.admit,
        )

    async def settle(self, usage: TokenUsagePayload | None) -> None:
        """Only final request usage is known; retry usage is not fabricated."""
        if self.settled:
            raise RuntimeError("Consolidation logical call was already settled.")
        if usage is not None and not self.reservations:
            raise RuntimeError("Consolidation usage has no admitted dispatch.")
        for index, reservation in enumerate(self.reservations):
            known = (
                scalar_consolidation_usage(usage)
                if index == len(self.reservations) - 1
                else None
            )
            exceeded = await self.repository.record_usage(
                self.principal,
                dispatch_id=reservation.dispatch_id,
                usage=known,
            )
            if exceeded:
                self.settled = True
                raise ConsolidationBudgetExceeded(
                    "Consolidation token budget is exhausted."
                )
        self.settled = True
