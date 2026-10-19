"""Context preparation preserves canonical history without ordinary turn effects."""

import pytest
from azcommon.result import Result
from pydantic import BaseModel
from pydantic_ai.messages import ModelMessagesTypeAdapter

from azents.core.agent import AgentModelSelection, SelectableModelCandidate
from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.core.routine_judgment_test import JUDGMENT_TIME, candidate
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.core.tools import (
    PreparedDynamicPrompt,
    Toolkit,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.events.openai_responses import OpenAIResponsesRequest
from azents.engine.events.pydantic_ai_types import PydanticAIRequest
from azents.engine.hooks.types import RuntimeHooks
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.routine_judgment_context import prepare_canonical_routine_judgment
from azents.engine.routine_judgment_test import history
from azents.engine.run.contracts import RunRequest, ToolkitBinding
from azents.engine.run.emit import PublishedEvent
from azents.services.model_file import ModelFileDownload, ModelFileResolveError
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)


class ContextToolkit(Toolkit[BaseModel]):
    """A real prompt provider, with ordinary hooks forbidden during judgment."""

    async def update_context(self, context: TurnContext) -> ToolkitState:
        assert context.session_id == "judgment-session"
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])

    async def get_static_prompt(self, context: TurnContext) -> str:
        return "Current Session static guidance."

    async def prepare_dynamic_prompt(
        self, context: TurnContext
    ) -> PreparedDynamicPrompt:
        return PreparedDynamicPrompt(
            text="Current Session continuity: keep the ordinary investigation intact.",
            native_replay_context="current-session-context",
        )

    def hooks(self) -> RuntimeHooks:
        raise AssertionError("Judgment must not enter the ordinary turn lifecycle.")


class UnusedFileDownloader:
    async def download_for_authority(
        self, *, model_file_id: str, authority: SessionResourceAuthority
    ) -> Result[ModelFileDownload, ModelFileResolveError]:
        raise AssertionError("This synthetic conversation has no file references.")


def request(selection: AgentModelSelection) -> RunRequest:
    return RunRequest(
        session_id="judgment-session",
        user_messages=[],
        agent_prompt="Ordinary Agent policy.",
        toolkits=[ToolkitBinding(ContextToolkit(), "context", "context", False)],
        model=selection.model_identifier,
        credential_kwargs={},
        workspace_id="workspace",
        agent_id="agent",
        tool_search_enabled=True,
        auto_compaction_threshold_tokens=None,
        enabled_execution_options=[],
        inference_state=None,
        compaction_provider_integration_id=None,
        model_assembly_metadata=ModelAssemblyMetadata.from_selection(selection),
        compaction_candidate=SelectableModelCandidate(
            model_selection=selection, settings=make_test_model_settings()
        ),
        top_k=None,
        provider=selection.provider,
        model_capabilities=selection.normalized_capabilities,
        model_developer=selection.model_developer,
    )


async def publish(event: PublishedEvent) -> None:
    raise AssertionError("Context preparation must not emit ordinary model events.")


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.OPENROUTER])
async def test_canonical_context_does_not_enter_ordinary_turn(
    provider: LLMProvider,
) -> None:
    selection = make_test_model_selection(
        provider=provider, model_identifier="fixture"
    ).model_copy(
        update={"normalized_capabilities": ModelCapabilities(structured_response=True)}
    )
    run_request = request(selection)
    transcript = history()
    original = list(transcript)
    prepared = await prepare_canonical_routine_judgment(
        run_request=run_request,
        model_selection=selection,
        transcript=transcript,
        candidates=(candidate(),),
        current_time=JUDGMENT_TIME,
        context=TurnContext(
            workspace_id="workspace",
            model="fixture",
            run_id="host-run",
            publish_event=publish,
            session_id="judgment-session",
        ),
        model_file_service=UnusedFileDownloader(),
    )
    assert transcript == original
    assert run_request.inference_state is None
    assert prepared.selection.provider == provider
    assert prepared.selection.model == "fixture"
    native = prepared.request
    if isinstance(native, OpenAIResponsesRequest):
        encoded = str(native.input)
        prompt = str(native.options)
        assert not native.tools
    else:
        assert isinstance(native, PydanticAIRequest)
        encoded = ModelMessagesTypeAdapter.dump_json(native.messages).decode()
        prompt = str(native.messages)
        assert not native.parameters.function_tools
    assert "Watch official launch announcements." in encoded
    assert "Only notify about confirmed news." in encoded
    assert "Ordinary Agent policy." in prompt
    assert "Current Session static guidance." in prompt
    assert "Current Session continuity" in prompt
    assert "Current time: 2026-10-19T09:58:00+00:00" in encoded
    assert "requested interval has not elapsed, set act=false" in encoded


async def test_foreign_context_rejected_before_toolkit_or_model_work() -> None:
    selection = make_test_model_selection(model_identifier="fixture")
    run_request = request(selection)
    with pytest.raises(ValueError, match="does not match"):
        await prepare_canonical_routine_judgment(
            run_request=run_request,
            model_selection=selection,
            transcript=history(),
            candidates=(candidate(),),
            current_time=JUDGMENT_TIME,
            context=TurnContext(
                workspace_id="other-workspace",
                model="fixture",
                run_id="host-run",
                publish_event=publish,
                session_id="judgment-session",
            ),
            model_file_service=UnusedFileDownloader(),
        )
