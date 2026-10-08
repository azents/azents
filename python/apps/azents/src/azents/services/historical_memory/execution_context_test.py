"""Actual lowered small-window context and common retained compaction evidence."""

import dataclasses

import sqlalchemy as sa

from azents.core.agent import SelectableModelCandidate
from azents.core.enums import EventKind
from azents.engine.context.compaction import SummaryModelCall
from azents.engine.run.model_transport import ModelTransportState
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.session_execution_file import RDBSessionExecutionFile
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.services.historical_memory.consolidation_host_test import (
    _call,
    _host,
    _ScriptedModel,
)


@dataclasses.dataclass
class _CompactingModel(_ScriptedModel):
    summary_inputs: list[str] = dataclasses.field(default_factory=list)

    @property
    def summary_call(self) -> SummaryModelCall:
        async def summarize(
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
            assert effective_input_tokens == 32_000
            assert session_id is not None
            self.summary_inputs.append(conversation_text)
            return (
                "memory-compaction-checkpoint: Current supplied files remain "
                "in inputs/. The execution has authored notes.md and must "
                "explicitly submit result.md. "
                "No submission has been accepted. Continue using the current files."
            )

        return summarize


async def test_small_resolved_window_uses_shared_compactor_and_retains_current_files(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    notes = "Current work remains in progress. " * 2_000
    model = _CompactingModel(
        [
            [
                _call(
                    "write",
                    "long-note",
                    {
                        "path": "azents://execution/notes.md",
                        "content": notes,
                        "overwrite": False,
                    },
                )
            ],
            [
                _call(
                    "write",
                    "result",
                    {
                        "path": "azents://execution/result.md",
                        "content": (
                            "# Current context\n"
                            "The verified task remains in progress.\n"
                        ),
                        "overwrite": False,
                    },
                ),
                _call(
                    "submit_memory",
                    "accepted",
                    {"path": "azents://execution/result.md"},
                ),
            ],
        ],
        close_failure=False,
        effective_input_tokens=32_000,
    )
    host = await _host(rdb_session_manager, model, max_turns=4)
    outcome = await host.run()
    assert outcome.tool_call_id == "accepted"
    assert len(model.contexts) == 2 and len(model.summary_inputs) == 1
    assert "memory-compaction-checkpoint" in model.prepared_inputs[-1]
    async with rdb_session_manager() as session:
        record = await session.read_session.get(
            RDBAgentSession, host.principal.owner.session_id
        )
        assert record is not None and record.model_input_head_event_id is not None
        head = await session.read_session.get(
            RDBEvent, record.model_input_head_event_id
        )
        assert head is not None and head.kind is EventKind.COMPACTION_SUMMARY
        events = list(
            await session.read_session.scalars(
                sa.select(RDBEvent)
                .where(RDBEvent.session_id == record.id)
                .order_by(RDBEvent.id)
            )
        )
        assert sum(event.kind is EventKind.COMPACTION_MARKER for event in events) == 1
        assert sum(event.kind is EventKind.COMPACTION_SUMMARY for event in events) == 1
        stored_notes = await session.read_session.get(
            RDBSessionExecutionFile, (record.id, "notes.md")
        )
        assert stored_notes is not None and stored_notes.content == notes
        assert (
            await session.read_session.scalar(
                sa.select(RDBSessionExecutionFile.path)
                .where(
                    RDBSessionExecutionFile.session_id == record.id,
                    RDBSessionExecutionFile.path.like("inputs/%"),
                    RDBSessionExecutionFile.writable.is_(False),
                )
                .limit(1)
            )
            is not None
        )
        assert any(event.id < head.id for event in events)
