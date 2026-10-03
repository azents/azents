"""Deterministic real-storage multi-turn internal Agent and fail-closed completion."""

import dataclasses
import json
import math
import re
from collections.abc import Sequence

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import AgentModelSelection
from azents.core.enums import EventKind
from azents.core.historical_memory_budget import ConsolidationBudgetExceeded
from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.core.historical_memory_publication import (
    ConsolidationOutputError,
    ValidatedConsolidationOverview,
)
from azents.engine.events.model_messages import (
    TransientModelMessage,
    transient_model_message,
)
from azents.engine.events.openai_responses import OpenAIResponsesLowerer
from azents.engine.events.protocols import NormalizedAdapterOutput
from azents.engine.events.tools import ToolCatalog
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    NativeArtifact,
    OutputTextPart,
    TokenUsagePayload,
    build_native_compat_key,
)
from azents.engine.model_stream import (
    InternalModelStreamCallContext,
    admit_model_dispatch,
)
from azents.rdb.models.historical_memory_consolidation import RDBConsolidationRevision
from azents.rdb.session import SessionManager
from azents.repos.historical_memory_consolidation.budget import (
    ConsolidationBudgetRepository,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
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
from azents.services.historical_memory.consolidation_host import (
    ConsolidationIterationHost,
)
from azents.services.historical_memory.consolidation_model import (
    PreparedConsolidationRequest,
)
from azents.services.historical_memory.consolidation_tools import (
    ConsolidationToolBindings,
)
from azents.services.historical_memory.draft_vfs import ConsolidationVfsObservations
from azents.testing.consolidation import seed_consolidation_corpus
from azents.testing.model_selection import make_test_model_selection


def _native() -> NativeArtifact:
    return NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="synthetic",
            native_format="test_output",
            provider="openai",
            model="gpt-4o",
            schema_version="1",
        ),
        adapter="synthetic",
        native_format="test_output",
        provider="openai",
        model="gpt-4o",
        schema_version="1",
        item={"type": "synthetic_completed_model_output"},
    )


@dataclasses.dataclass
class _ScriptedModel:
    selection: AgentModelSelection
    empty: bool
    invalid_final: bool
    hard_input: bool
    source_uri: str | None = dataclasses.field(init=False, default=None)
    work_id: str | None = dataclasses.field(init=False, default=None)
    turn: int = dataclasses.field(init=False, default=0)
    closed: bool = dataclasses.field(init=False, default=False)
    requests: list[str] = dataclasses.field(init=False, default_factory=list)
    feedback: list[ClientToolResultPayload] = dataclasses.field(
        init=False, default_factory=list
    )
    names: set[str] = dataclasses.field(init=False, default_factory=set)

    @property
    def effective_input_tokens(self) -> int:
        return 128000

    @property
    def max_output_tokens(self) -> int:
        return 2500

    def prepare(
        self,
        messages: Sequence[TransientModelMessage],
        catalog: ToolCatalog,
        *,
        system_prompt: str,
        output_tokens: int,
    ) -> PreparedConsolidationRequest:
        self.names.update(catalog.tools)
        self.feedback = [
            message.payload
            for message in messages
            if isinstance(message.payload, ClientToolResultPayload)
        ]
        text = "\n".join(
            part.text
            for result in self.feedback
            for part in result.output
            if isinstance(part, OutputTextPart)
        )
        match = re.search(
            r"Work ([a-f0-9]{32});.*?(azents://memory/historical/[^\s]+)", text
        )
        if match is not None:
            self.work_id, self.source_uri = match.group(1), match.group(2)
        request = OpenAIResponsesLowerer(
            top_k=None,
            provider="openai",
            provider_id=self.selection.provider,
            model=self.selection.model_identifier,
            tools=catalog.native_tools_for(catalog.direct_tool_names),
            supported_execution_options=(),
            enabled_execution_options=(),
            max_output_tokens=output_tokens,
        ).lower(
            messages,
            native_replay_context=None,
            model=self.selection.model_identifier,
            system_prompt=system_prompt,
        )
        self.requests.append(str(request))
        estimate = (
            100000
            if self.hard_input
            else math.ceil(request.native_request_input_chars() / 0.75)
        )
        return PreparedConsolidationRequest(request, estimate, output_tokens)

    async def invoke(
        self,
        prepared: PreparedConsolidationRequest,
        *,
        context: InternalModelStreamCallContext,
    ) -> NormalizedAdapterOutput[TransientModelMessage]:
        assert context.session_id is context.run_id is None
        await admit_model_dispatch(context)
        turn = self.turn
        self.turn += 1
        if self.invalid_final:
            turn = 7
        uri = "azents://memory-draft/summary.md"
        name: str
        arguments: dict[str, str]
        if turn == 0:
            name, arguments = (
                "read",
                {"path": "azents://memory/inventory/work/README.md"},
            )
        elif turn == 1:
            assert self.source_uri is not None
            name, arguments = "read", {"path": self.source_uri}
        elif turn == 2:
            name, arguments = "read", {"path": uri}
        elif turn == 3:
            assert self.source_uri is not None
            content = (
                "## Historical Context\n\n## Source Routes\n"
                if self.empty
                else (
                    "## Historical Context\nSource-dependent continuation context.\n\n"
                    f"## Source Routes\n- {self.source_uri} — Scoped source details\n"
                )
            )
            name, arguments = "write", {"path": uri, "content": content}
        elif turn == 4:
            name, arguments = (
                "edit",
                {
                    "path": uri,
                    "old_string": "absent exact text",
                    "new_string": "never committed",
                },
            )
        elif turn == 5:
            name, arguments = (
                "edit",
                {
                    "path": uri,
                    "old_string": "## Historical Context",
                    "new_string": "## Historical Context",
                },
            )
        elif turn == 6:
            assert self.work_id is not None
            coverage = {
                "dispositions": [
                    {
                        "work_id": self.work_id,
                        "action": "omitted" if self.empty else "considered",
                        "reason": "No useful continuation context"
                        if self.empty
                        else "Integrated source context",
                    }
                ]
            }
            name, arguments = (
                "write",
                {
                    "path": "azents://memory-draft/coverage.json",
                    "content": json.dumps(coverage),
                },
            )
        else:
            return NormalizedAdapterOutput[TransientModelMessage](
                needs_follow_up=False,
                events=[
                    transient_model_message(
                        EventKind.ASSISTANT_MESSAGE,
                        AssistantMessagePayload(
                            content=(
                                "Untrusted final prose is not a publication payload."
                            ),
                            native_artifact=_native(),
                        ),
                    )
                ],
                usage=TokenUsagePayload(
                    prompt_tokens=20, completion_tokens=5, total_tokens=25, raw={}
                ),
            )
        return NormalizedAdapterOutput[TransientModelMessage](
            needs_follow_up=True,
            events=[
                transient_model_message(
                    EventKind.CLIENT_TOOL_CALL,
                    ClientToolCallPayload(
                        call_id=f"step-{turn}",
                        name=name,
                        arguments=json.dumps(arguments),
                        wire_dialect="json_function",
                        native_artifact=_native(),
                    ),
                )
            ],
            usage=TokenUsagePayload(
                prompt_tokens=20, completion_tokens=5, total_tokens=25, raw={}
            ),
        )

    async def close(self) -> None:
        self.closed = True


async def _host(
    manager: SessionManager[AsyncSession],
    *,
    personal: bool,
    empty: bool,
    invalid_final: bool,
    hard_input: bool,
) -> ConsolidationIterationHost:
    corpus = await seed_consolidation_corpus(manager)
    ownership = ConsolidationOwnershipRepository(manager)
    claim = await ownership.claim(corpus.personal if personal else corpus.team)
    assert claim is not None
    await ConsolidationRecoveryRepository(manager).prepare(claim.principal)
    work = ConsolidationWorkRepository(manager)
    tools = ConsolidationToolBindings(
        ConsolidationVfsObservations(claim.principal),
        ConsolidationDraftRepository(manager),
        ConsolidationSourceRepository(manager),
        work,
        ownership,
    )
    model = _ScriptedModel(
        make_test_model_selection(), empty, invalid_final, hard_input
    )
    return ConsolidationIterationHost(
        claim,
        model,
        tools,
        ConsolidationBudgetRepository(manager),
        ownership,
        work,
        ConsolidationPublicationRepository(manager),
    )


@pytest.mark.parametrize("personal", [False, True])
@pytest.mark.parametrize("empty", [False, True])
async def test_multi_turn_shared_host_edits_handles_errors_and_publishes_files(
    rdb_session_manager: SessionManager[AsyncSession],
    personal: bool,
    empty: bool,
) -> None:
    host = await _host(
        rdb_session_manager,
        personal=personal,
        empty=empty,
        invalid_final=False,
        hard_input=False,
    )
    model = host.model
    assert isinstance(model, _ScriptedModel)
    outcome = await host.run()
    assert model.turn == 8 and model.closed and host.closed
    assert host.messages == [] and host.tools.observations.files == {}
    assert {"read", "grep", "glob", "write", "edit", "delete"} <= model.names
    assert not model.names & {
        "exec_command",
        "save_memory",
        "spawn_agent",
        "load_skill",
        "submit",
    }
    assert any(
        result.status == "failed" and result.name == "edit" for result in model.feedback
    )
    forbidden_scope = "team" if personal else "user"
    assert all(
        f"azents://memory/historical/{forbidden_scope}/" not in request
        for request in model.requests
    )
    assert all("combined budget" not in request.lower() for request in model.requests)
    async with rdb_session_manager() as session:
        revision = await session.get(RDBConsolidationRevision, outcome.revision_id)
        assert revision is not None
        assert "Untrusted final prose" not in revision.markdown
        assert (revision.rendered_block == "") == empty
        assert "never committed" not in revision.markdown
    inspected = await host.publication_repository.inspect_outcome(host.claim.principal)
    assert inspected is not None and inspected == outcome


async def test_normal_final_response_without_valid_files_is_not_success(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    host = await _host(
        rdb_session_manager,
        personal=False,
        empty=False,
        invalid_final=True,
        hard_input=False,
    )
    with pytest.raises(ConsolidationOutputError):
        await host.run()
    assert host.closed and host.messages == []
    assert (
        await host.publication_repository.inspect_outcome(host.claim.principal) is None
    )


async def test_input_checkpoint_stops_before_any_physical_request_or_publication(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    host = await _host(
        rdb_session_manager,
        personal=False,
        empty=False,
        invalid_final=False,
        hard_input=True,
    )
    with pytest.raises(ConsolidationBudgetExceeded, match="checkpoint"):
        await host.run()
    model = host.model
    assert isinstance(model, _ScriptedModel) and model.turn == 0 and model.closed
    assert (
        await host.budget_repository.remaining(host.claim.principal)
    ).model_requests == 32
    assert (
        await host.publication_repository.inspect_outcome(host.claim.principal) is None
    )


class _UncertainPublication(ConsolidationPublicationRepository):
    async def publish(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        expected_draft_revision_id: str,
        expected_observation_epoch: int,
        overview: ValidatedConsolidationOverview,
    ) -> ConsolidationPublicationOutcome:
        await super().publish(
            principal,
            expected_draft_revision_id=expected_draft_revision_id,
            expected_observation_epoch=expected_observation_epoch,
            overview=overview,
        )
        raise OperationalError(
            "Synthetic publication result loss", None, RuntimeError("Result lost")
        )


async def test_uncertain_commit_inspects_original_outcome_without_repeat_publication(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    host = await _host(
        rdb_session_manager,
        personal=False,
        empty=False,
        invalid_final=False,
        hard_input=False,
    )
    host.publication_repository = _UncertainPublication(rdb_session_manager)
    outcome = await host.run()
    assert host.closed and host.messages == []
    assert (
        await host.publication_repository.inspect_outcome(host.claim.principal)
        == outcome
    )
    async with rdb_session_manager() as session:
        count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBConsolidationRevision)
            .where(RDBConsolidationRevision.unit_id == host.claim.unit_id)
        )
        assert count == 1
