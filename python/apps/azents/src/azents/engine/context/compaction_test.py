"""Checkpoint representation and selected-model compaction execution contracts."""

import dataclasses
from unittest.mock import AsyncMock

import httpx2
import pytest
from anthropic import BadRequestError

from azents.core.agent import SelectableModelCandidate
from azents.core.enums import LLMProvider
from azents.core.openai_client_config import OpenAIResponsesClientConfig
from azents.engine.context.compaction import (
    SUMMARY_SYSTEM_PROMPT,
    SUMMARY_USER_TEMPLATE,
    CompactionSummaryBudget,
    compute_summary_budget,
    enforce_summary_char_budget,
    summarize_text_with_model,
)
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.run.errors import (
    CompactionModelStreamTimeoutError,
    ModelStreamTimeoutError,
)
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
)
from azents.services.historical_memory.preparation_test import _SummaryClient
from azents.testing.model_selection import (
    make_test_model_candidate,
    make_test_model_selection,
    make_test_model_settings,
)
from azents.testing.model_stream import make_test_model_stream_watchdog


@pytest.mark.parametrize(
    "window,expected",
    [
        (32000, CompactionSummaryBudget(12000, 16000, 18000)),
        (128000, CompactionSummaryBudget(15000, 41000, 46000)),
        (200000, CompactionSummaryBudget(24000, 50000, 55000)),
    ],
)
def test_checkpoint_representation_scales_with_context(
    window: int, expected: CompactionSummaryBudget
) -> None:
    assert compute_summary_budget(window) == expected


def test_checkpoint_unknown_window_uses_default_context() -> None:
    assert compute_summary_budget(None) == compute_summary_budget(128000)


def test_checkpoint_guard_accepts_tolerated_size_and_marks_truncation() -> None:
    budget = compute_summary_budget(32000)
    within = "a" * 17999
    assert enforce_summary_char_budget(within, budget) == within
    output = enforce_summary_char_budget("a" * 20000, budget)
    assert len(output) <= budget.truncate_chars
    assert output.endswith("[Truncated by Azents compaction guard.]")


def test_checkpoint_prompt_preserves_execution_ready_handoff_contract() -> None:
    prompt = " ".join(SUMMARY_SYSTEM_PROMPT.split())
    for fragment in (
        "execution-ready handoff checkpoint",
        "applying the transcript chronologically",
        "state transitions that update the working direction",
        "most advanced validated state",
        "furthest verified progress",
        "order next actions by execution priority",
        "retaining continuation-relevant state and evidence",
        "including evidence of completed work",
        "let task complexity determine length",
        "Needs verification",
        "Output only the checkpoint",
    ):
        assert fragment in prompt
    for section in (
        "## Active Objective",
        "## Current Execution State",
        "## Completed Work",
        "## Next Actions",
        "## Active Constraints and Decisions",
        "## Relevant Files and Identifiers",
        "## Verification",
        "## References",
    ):
        assert section in SUMMARY_USER_TEMPLATE
    template = " ".join(SUMMARY_USER_TEMPLATE.split())
    for fragment in (
        "Process the transcript in chronological order",
        "Later user direction updates the active objective",
        "Completed actions update the execution state",
        "previous state to update",
        "furthest completed and verified progress",
        "concrete, ordered",
        "bounded recent user-message and transcript excerpts",
    ):
        assert fragment in template


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH])
@pytest.mark.parametrize("selected_tokens", [None, 6400])
async def test_compaction_native_sdk_uses_captured_candidate_and_prompts(
    provider: LLMProvider,
    selected_tokens: int | None,
) -> None:
    client = _SummaryClient("Execution checkpoint")

    def factory(*, config: OpenAIResponsesClientConfig) -> _SummaryClient:
        return client

    candidate = SelectableModelCandidate(
        model_selection=make_test_model_selection(provider=provider),
        settings=make_test_model_settings().model_copy(
            update={"max_output_tokens": selected_tokens}
        ),
    )
    candidate.model_selection.normalized_capabilities.parameters.max_output_tokens = (
        selected_tokens is not None
    )
    summary = await summarize_text_with_model(
        sdk_factories=dataclasses.replace(
            get_model_sdk_factories(), openai_responses=factory
        ),
        watchdog=make_test_model_stream_watchdog(),
        candidate=candidate,
        credential_kwargs={"api_key": "synthetic-unused"},
        effective_input_tokens=128000,
        websocket_enabled=False,
        transport_state=None,
        system_prompt="Summarize the current state",
        user_prompt="Checkpoint prefix\n",
        conversation_text="[User]: latest state",
        session_id="session-1",
    )
    assert summary == "Execution checkpoint"
    assert client.closed and len(client.requests) == 1
    assert client.requests[0]["model"] == candidate.model_selection.model_identifier
    assert client.requests[0]["instructions"] == "Summarize the current state"
    assert client.requests[0]["input"] == [
        {"role": "user", "content": "Checkpoint prefix\n[User]: latest state"}
    ]


async def test_compaction_classifies_shared_stream_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeout = ModelStreamTimeoutError(
        timeout_kind="parsed_event_idle",
        deadline_seconds=5,
        elapsed_seconds=5,
        call_kind="compaction",
        provider="openai",
        model="gpt-4o",
    )
    monkeypatch.setattr(
        "azents.engine.context.compaction.call_model_operation_text_with_usage",
        AsyncMock(side_effect=timeout),
    )
    with pytest.raises(CompactionModelStreamTimeoutError) as caught:
        await summarize_text_with_model(
            sdk_factories=get_model_sdk_factories(),
            watchdog=make_test_model_stream_watchdog(),
            candidate=make_test_model_candidate(),
            credential_kwargs={"api_key": "synthetic-unused"},
            effective_input_tokens=128000,
            websocket_enabled=False,
            transport_state=None,
            system_prompt="Summary",
            user_prompt="Prefix",
            conversation_text="Source",
            session_id="session-1",
        )
    assert caught.value.failure_code == "model_stream_idle_timeout"
    assert caught.value.timeout_kind == "parsed_event_idle"


async def test_compaction_maps_native_context_failure_with_exact_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = BadRequestError(
        "Context exhausted",
        response=httpx2.Response(
            400, request=httpx2.Request("POST", "https://synthetic.invalid/messages")
        ),
        body={
            "error": {"type": "context_length_exceeded", "message": "Input too long"}
        },
    )
    operation = AsyncMock(side_effect=failure)
    monkeypatch.setattr(
        "azents.engine.context.compaction.call_model_operation_text_with_usage",
        operation,
    )
    candidate = SelectableModelCandidate(
        model_selection=make_test_model_selection(
            provider=LLMProvider.ANTHROPIC, model_identifier="publisher/exact/model"
        ),
        settings=make_test_model_settings(),
    )
    with pytest.raises(ModelProviderFailure) as caught:
        await summarize_text_with_model(
            sdk_factories=get_model_sdk_factories(),
            watchdog=make_test_model_stream_watchdog(),
            candidate=candidate,
            credential_kwargs={"api_key": "synthetic-unused"},
            effective_input_tokens=128000,
            websocket_enabled=False,
            transport_state=None,
            system_prompt="Summary",
            user_prompt="Prefix",
            conversation_text="Source",
            session_id="session-1",
        )
    operation.assert_awaited_once()
    assert caught.value.operation == "compaction"
    assert caught.value.category is ModelProviderFailureCategory.CONTEXT_LIMIT
    assert caught.value.route_model == "publisher/exact/model"
