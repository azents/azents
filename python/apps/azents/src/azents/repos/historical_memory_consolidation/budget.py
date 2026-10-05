"""Fenced observational dispatch/tool journals and idempotent scalar usage."""

from dataclasses import dataclass

import sqlalchemy as sa

from azents.core.historical_memory_budget import (
    ConsolidationDispatchReservation,
    ConsolidationUsage,
)
from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationDraft,
    RDBConsolidationModelDispatch,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
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
from azents.repos.historical_memory_consolidation.participant_types import (
    DraftParticipants,
)
from azents.repos.historical_memory_consolidation.retry import (
    retry_consolidation_operation,
)


async def check_input_influence(
    session: WriteSession,
    principal: ConsolidationJobPrincipal,
    owner: LockedConsolidationOwner,
) -> None:
    draft = await session.write_session.scalar(
        sa.select(RDBConsolidationDraft).where(
            RDBConsolidationDraft.unit_id == owner.unit.id
        )
    )
    if draft is None:
        raise ConsolidationAuthorityError("Consolidation input draft is unavailable.")
    await check_draft_influence(session, principal=principal, owner=owner, draft=draft)


@dataclass(frozen=True)
class ConsolidationExecutionRepository:
    """Journal physical execution without granting budget authority to counters."""

    session_manager: SessionManager[WriteSession]

    @retry_consolidation_operation
    async def authorize(self, principal: ConsolidationJobPrincipal) -> None:
        async with consolidation_job_session(
            self.session_manager,
            principal,
            participants=DraftParticipants(recovery=False),
        ) as job:
            await check_input_influence(job.session, principal, job.owner)
            await require_commit_owner(job.session, job.owner)

    @retry_consolidation_operation
    async def reserve_model(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        dispatch_id: str,
        input_tokens: int,
        output_tokens: int | None,
    ) -> ConsolidationDispatchReservation:
        if (
            len(dispatch_id) != 32
            or input_tokens < 0
            or (output_tokens is not None and output_tokens < 1)
        ):
            raise ValueError("Consolidation model request observation is invalid.")
        async with consolidation_job_session(
            self.session_manager,
            principal,
            participants=DraftParticipants(recovery=False),
        ) as job:
            session, owner = job.session, job.owner
            await check_input_influence(session, principal, owner)
            previous = await session.write_session.get(
                RDBConsolidationModelDispatch, (principal.attempt_id, dispatch_id)
            )
            if previous is not None:
                if (
                    previous.reserved_input_tokens != input_tokens
                    or previous.reserved_output_tokens != output_tokens
                ):
                    raise ConsolidationDraftConflict(
                        "Consolidation dispatch observation conflicts."
                    )
                result = ConsolidationDispatchReservation(
                    dispatch_id, previous.request_number, input_tokens, output_tokens
                )
            else:
                owner.attempt.model_requests += 1
                session.write_session.add(
                    RDBConsolidationModelDispatch(
                        attempt_id=principal.attempt_id,
                        dispatch_id=dispatch_id,
                        request_number=owner.attempt.model_requests,
                        reserved_input_tokens=input_tokens,
                        reserved_output_tokens=output_tokens,
                    )
                )
                result = ConsolidationDispatchReservation(
                    dispatch_id,
                    owner.attempt.model_requests,
                    input_tokens,
                    output_tokens,
                )
            await require_commit_owner(session, owner)
        return result

    @retry_consolidation_operation
    async def record_usage(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        dispatch_id: str,
        usage: ConsolidationUsage | None,
    ) -> None:
        """Retain unknown per-dispatch usage; sum only reported actual tokens."""
        async with consolidation_job_session(
            self.session_manager, principal, participants=None
        ) as job:
            session, owner = job.session, job.owner
            row = await session.write_session.get(
                RDBConsolidationModelDispatch, (principal.attempt_id, dispatch_id)
            )
            if row is None:
                raise ConsolidationDraftConflict(
                    "Consolidation dispatch observation is absent."
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
                    owner.attempt.input_tokens += usage.prompt_tokens
                    owner.attempt.output_tokens += usage.completion_tokens
                    row.usage_json = usage.model_dump(mode="json")
                row.usage_recorded = True
            await require_commit_owner(session, owner)

    @retry_consolidation_operation
    async def reserve_tools(
        self, principal: ConsolidationJobPrincipal, *, count: int
    ) -> None:
        if count < 1:
            raise ValueError("Consolidation tool count must be positive.")
        async with consolidation_job_session(
            self.session_manager,
            principal,
            participants=DraftParticipants(recovery=False),
        ) as job:
            await check_input_influence(job.session, principal, job.owner)
            job.owner.attempt.tool_calls += count
            await require_commit_owner(job.session, job.owner)
