"""Fenced physical-dispatch/tool admission and idempotent scalar usage accounting."""

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.historical_memory_budget import (
    CONSOLIDATION_INPUT_TOKEN_LIMIT,
    CONSOLIDATION_MODEL_REQUEST_LIMIT,
    CONSOLIDATION_OUTPUT_TOKEN_LIMIT,
    CONSOLIDATION_TOOL_CALL_LIMIT,
    ConsolidationBudgetExceeded,
    ConsolidationDispatchReservation,
    ConsolidationUsage,
)
from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationDraft,
    RDBConsolidationModelDispatch,
)
from azents.rdb.session import SessionManager
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
    LockedConsolidationOwner,
    consolidation_job_session,
    require_commit_owner,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftConflict,
    check_draft_influence,
)


@dataclass(frozen=True)
class ConsolidationRemainingBudget:
    model_requests: int
    input_tokens: int
    output_tokens: int
    tool_calls: int


async def check_input_influence(
    session: AsyncSession,
    principal: ConsolidationJobPrincipal,
    owner: LockedConsolidationOwner,
) -> None:
    draft = await session.scalar(
        sa.select(RDBConsolidationDraft).where(
            RDBConsolidationDraft.unit_id == owner.unit.id
        )
    )
    if draft is None:
        raise ConsolidationAuthorityError("Consolidation input draft is unavailable.")
    await check_draft_influence(session, principal=principal, owner=owner, draft=draft)


@dataclass(frozen=True)
class ConsolidationBudgetRepository:
    """Reservations commit before physical SDK I/O; unknown usage stays reserved."""

    session_manager: SessionManager[AsyncSession]

    async def remaining(
        self, principal: ConsolidationJobPrincipal
    ) -> ConsolidationRemainingBudget:
        async with consolidation_job_session(self.session_manager, principal) as job:
            await check_input_influence(job.session, principal, job.owner)
            attempt = job.owner.attempt
            if attempt.failure_code == "token_budget_exceeded":
                raise ConsolidationBudgetExceeded(
                    "Consolidation token budget is exhausted."
                )
            result = ConsolidationRemainingBudget(
                max(0, CONSOLIDATION_MODEL_REQUEST_LIMIT - attempt.model_requests),
                max(0, CONSOLIDATION_INPUT_TOKEN_LIMIT - attempt.input_tokens),
                max(0, CONSOLIDATION_OUTPUT_TOKEN_LIMIT - attempt.output_tokens),
                max(0, CONSOLIDATION_TOOL_CALL_LIMIT - attempt.tool_calls),
            )
            await require_commit_owner(job.session, job.owner)
        return result

    async def reserve_model(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        dispatch_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> ConsolidationDispatchReservation:
        if len(dispatch_id) != 32 or input_tokens < 0 or output_tokens < 1:
            raise ValueError("Consolidation model reservation is invalid.")
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            await check_input_influence(session, principal, owner)
            previous = await session.get(
                RDBConsolidationModelDispatch, (principal.attempt_id, dispatch_id)
            )
            if previous is not None:
                if (
                    previous.reserved_input_tokens != input_tokens
                    or previous.reserved_output_tokens != output_tokens
                ):
                    raise ConsolidationDraftConflict(
                        "Consolidation dispatch reservation conflicts."
                    )
                result = ConsolidationDispatchReservation(
                    dispatch_id, previous.request_number, input_tokens, output_tokens
                )
            else:
                attempt = owner.attempt
                if (
                    attempt.failure_code == "token_budget_exceeded"
                    or attempt.model_requests >= CONSOLIDATION_MODEL_REQUEST_LIMIT
                    or attempt.input_tokens + input_tokens
                    > CONSOLIDATION_INPUT_TOKEN_LIMIT
                    or attempt.output_tokens + output_tokens
                    > CONSOLIDATION_OUTPUT_TOKEN_LIMIT
                ):
                    raise ConsolidationBudgetExceeded(
                        "Consolidation model budget is exhausted."
                    )
                attempt.model_requests += 1
                attempt.input_tokens += input_tokens
                attempt.output_tokens += output_tokens
                session.add(
                    RDBConsolidationModelDispatch(
                        attempt_id=principal.attempt_id,
                        dispatch_id=dispatch_id,
                        request_number=attempt.model_requests,
                        reserved_input_tokens=input_tokens,
                        reserved_output_tokens=output_tokens,
                    )
                )
                result = ConsolidationDispatchReservation(
                    dispatch_id, attempt.model_requests, input_tokens, output_tokens
                )
            await require_commit_owner(session, owner)
        return result

    async def record_usage(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        dispatch_id: str,
        usage: ConsolidationUsage | None,
    ) -> bool:
        """Return an over-budget signal after durable accounting, not a rollback."""
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            row = await session.get(
                RDBConsolidationModelDispatch, (principal.attempt_id, dispatch_id)
            )
            if row is None:
                raise ConsolidationDraftConflict(
                    "Consolidation dispatch reservation is absent."
                )
            previous_usage = (
                None
                if row.usage_json is None
                else ConsolidationUsage.model_validate(row.usage_json)
            )
            if row.usage_recorded:
                if previous_usage != usage:
                    raise ConsolidationDraftConflict(
                        "Consolidation usage replay conflicts."
                    )
            else:
                if usage is not None:
                    owner.attempt.input_tokens += (
                        usage.prompt_tokens - row.reserved_input_tokens
                    )
                    owner.attempt.output_tokens += (
                        usage.completion_tokens - row.reserved_output_tokens
                    )
                    row.usage_json = usage.model_dump(mode="json")
                row.usage_recorded = True
            exceeded = (
                owner.attempt.input_tokens > CONSOLIDATION_INPUT_TOKEN_LIMIT
                or owner.attempt.output_tokens > CONSOLIDATION_OUTPUT_TOKEN_LIMIT
            )
            if exceeded:
                owner.attempt.failure_code = "token_budget_exceeded"
            await require_commit_owner(session, owner)
        return exceeded

    async def reserve_tools(
        self, principal: ConsolidationJobPrincipal, *, count: int
    ) -> None:
        if count < 1:
            raise ValueError("Consolidation tool reservation must be positive.")
        async with consolidation_job_session(self.session_manager, principal) as job:
            await check_input_influence(job.session, principal, job.owner)
            if (
                job.owner.attempt.failure_code == "token_budget_exceeded"
                or job.owner.attempt.tool_calls + count > CONSOLIDATION_TOOL_CALL_LIMIT
            ):
                raise ConsolidationBudgetExceeded(
                    "Consolidation tool budget is exhausted."
                )
            job.owner.attempt.tool_calls += count
            await require_commit_owner(job.session, job.owner)
