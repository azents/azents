"""Common durable context/head and append-only compaction for Memory execution."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.enums import AgentRunPhase, EventKind
from azents.core.historical_memory_consolidation import (
    MemoryAcceptedOutcome,
    MemoryExecutionPrincipal,
)
from azents.engine.context.compaction import (
    SUMMARY_SYSTEM_PROMPT,
    SUMMARY_USER_TEMPLATE,
    CompactionSummaryBudget,
    enforce_summary_char_budget,
)
from azents.engine.context.window import compute_auto_compaction_threshold_tokens
from azents.engine.events.engine_adapter import (
    _render_events_for_summary,
    _summary_input_char_budget,
)
from azents.engine.events.filters import EventCompactor
from azents.engine.events.model_messages import (
    TransientModelMessage,
    transient_model_message,
)
from azents.engine.events.system_reminders import (
    format_compaction_summary_reminder,
    format_plain_system_reminder,
)
from azents.engine.events.tools import ToolCatalog
from azents.engine.events.types import (
    CompactionSummaryPayload,
    Event,
    SystemReminderPayload,
    TokenUsagePayload,
    UserMessagePayload,
)
from azents.engine.provider_model_operation import PreparedModelOperation
from azents.engine.run.errors import CompactionFailedError
from azents.repos.compaction_operation import (
    CompactionCommitContext,
    CompactionOperationRepository,
    get_compaction_operation_repository,
)
from azents.repos.memory_execution_events import MemoryExecutionEventsRepository
from azents.services.historical_memory.consolidation_model import ConsolidationModelPort

_INPUT_KINDS = frozenset(
    {
        EventKind.USER_MESSAGE,
        EventKind.ASSISTANT_MESSAGE,
        EventKind.REASONING,
        EventKind.CLIENT_TOOL_CALL,
        EventKind.CLIENT_TOOL_RESULT,
        EventKind.PROVIDER_TOOL_CALL,
        EventKind.UNKNOWN_ADAPTER_OUTPUT,
    }
)


def current_model_messages(events: Sequence[Event]) -> list[TransientModelMessage]:
    """Project canonical history with the shared reminder presentation semantics."""
    messages: list[TransientModelMessage] = []
    for event in events:
        payload = event.payload
        if isinstance(payload, CompactionSummaryPayload):
            messages.append(
                transient_model_message(
                    EventKind.USER_MESSAGE,
                    UserMessagePayload(
                        sender_user_id=None,
                        content=format_compaction_summary_reminder(payload.content),
                    ),
                )
            )
        elif isinstance(payload, SystemReminderPayload):
            messages.append(
                transient_model_message(
                    EventKind.USER_MESSAGE,
                    UserMessagePayload(
                        sender_user_id=None,
                        content=format_plain_system_reminder(payload.text),
                    ),
                )
            )
        elif event.kind in _INPUT_KINDS:
            messages.append(transient_model_message(event.kind, payload))
    return messages


@dataclasses.dataclass(frozen=True)
class MemoryExecutionContextService:
    """Use the common EventCompactor and current canonical Session input head."""

    repository: Annotated[
        MemoryExecutionEventsRepository, Depends(MemoryExecutionEventsRepository)
    ]
    compaction_operations: Annotated[
        CompactionOperationRepository, Depends(get_compaction_operation_repository)
    ]

    async def seed(self, principal: MemoryExecutionPrincipal, content: str) -> None:
        await self.repository.seed(principal, content)

    async def append(
        self,
        principal: MemoryExecutionPrincipal,
        messages: Sequence[TransientModelMessage],
        *,
        accepted: MemoryAcceptedOutcome | None,
    ) -> None:
        await self.repository.append(principal, messages, accepted=accepted)

    async def record_usage(
        self, principal: MemoryExecutionPrincipal, usage: TokenUsagePayload | None
    ) -> None:
        await self.repository.record_usage(principal, usage)

    async def prepare(
        self,
        principal: MemoryExecutionPrincipal,
        model: ConsolidationModelPort,
        catalog: ToolCatalog,
        system_prompt: str,
    ) -> PreparedModelOperation:
        """Fit actual lowered input while preserving files through common compaction."""
        transcript = await self.repository.transcript(principal)
        prepared = model.prepare(
            current_model_messages(transcript),
            catalog,
            system_prompt=system_prompt,
            output_tokens=model.max_output_tokens,
        )
        threshold = compute_auto_compaction_threshold_tokens(
            model.effective_input_tokens
        )
        if prepared.input_tokens <= threshold:
            return prepared

        async def summarize(
            events: Sequence[Event], budget: CompactionSummaryBudget
        ) -> str:
            conversation = _render_events_for_summary(
                events,
                max_chars=_summary_input_char_budget(
                    model.effective_input_tokens, model.max_output_tokens
                ),
            )
            summary = await model.summary_call(
                candidate=model.candidate,
                credential_kwargs=dict(model.credential_kwargs),
                effective_input_tokens=model.effective_input_tokens,
                transport_state=model.transport_state,
                system_prompt=SUMMARY_SYSTEM_PROMPT,
                user_prompt=SUMMARY_USER_TEMPLATE,
                conversation_text=conversation,
                session_id=principal.owner.session_id,
            )
            return enforce_summary_char_budget(summary, budget)

        await self.repository.phase(principal, AgentRunPhase.COMPACTING)
        compactor = EventCompactor(
            operation_repository=self.compaction_operations.for_execution(
                principal.owner
            ),
            summary_context_window_tokens=model.effective_input_tokens,
        )
        await compactor.compact(
            session_id=principal.owner.session_id,
            transcript=transcript,
            compaction_id=uuid7().hex,
            summarize=summarize,
            summary_context_window_tokens=model.effective_input_tokens,
            reason="automatic_context_window",
            commit_context=CompactionCommitContext(
                workspace_id=principal.binding.unit.workspace_id,
                agent_id=principal.binding.unit.agent_id,
                run_id=principal.run_id,
                owner_generation=principal.owner.owner_generation,
                settle_model_operation=True,
            ),
        )
        transcript = await self.repository.transcript(principal)
        prepared = model.prepare(
            current_model_messages(transcript),
            catalog,
            system_prompt=system_prompt,
            output_tokens=model.max_output_tokens,
        )
        if prepared.input_tokens > model.effective_input_tokens:
            raise CompactionFailedError(
                "Prepared request exceeds the selected model input window."
            )
        await self.repository.phase(principal, AgentRunPhase.PREPARING_INPUT)
        return prepared
