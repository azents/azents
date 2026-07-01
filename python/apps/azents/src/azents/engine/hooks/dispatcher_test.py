"""runtime hook dispatcher tests."""

import asyncio
from typing import Never

from pytest import MonkeyPatch

from azents.engine.hooks import dispatcher as dispatcher_module
from azents.engine.hooks.dispatcher import (
    RuntimeHookDispatcher,
    RuntimeHookProviderRef,
)
from azents.engine.hooks.testing import (
    DeterministicHookAction,
    DeterministicRuntimeHookProvider,
)
from azents.engine.hooks.trace import (
    InMemoryRuntimeHookTraceSink,
    RuntimeHookTraceEvent,
)
from azents.engine.hooks.types import (
    AfterToolCallHookContext,
    BeforeToolCallHookContext,
    CompactionSummaryHookContext,
    CompactionSummaryReplace,
    RunStartHookContext,
    ToolCallDeny,
    ToolOutputReplace,
    TurnInjectedPrompt,
    TurnStartHookContext,
    TurnStartResult,
)


class _FailingTraceSink:
    """Trace sink that always fails."""

    async def record(self, event: RuntimeHookTraceEvent) -> None:
        """Reproduce trace sink failure."""
        raise RuntimeError("trace sink failed")


class _HooksFailingProvider(DeterministicRuntimeHookProvider):
    """Provider that reproduces hooks() resolve failure."""

    def hooks(self) -> Never:
        """Fail during mapping resolve phase."""
        raise RuntimeError("cannot build hooks")


def _provider_ref(provider: DeterministicRuntimeHookProvider) -> RuntimeHookProviderRef:
    """Create provider ref for tests."""
    return RuntimeHookProviderRef(slug=provider.slug, toolkit=provider)


def _run_start_context() -> RunStartHookContext:
    """Create run start context for tests."""
    return RunStartHookContext(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
    )


def _turn_start_context() -> TurnStartHookContext:
    """Create turn start context for tests."""
    return TurnStartHookContext(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
        turn_index=1,
    )


def _before_context() -> BeforeToolCallHookContext:
    """Create before tool context for tests."""
    return BeforeToolCallHookContext(
        tool_name="read_file",
        toolkit_slug="shell",
        args_json='{"secret":"RAW-ARGS-MARKER"}',
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
    )


def _after_context() -> AfterToolCallHookContext:
    """Create after tool context for tests."""
    return AfterToolCallHookContext(
        tool_name="read_file",
        toolkit_slug="shell",
        args_json='{"secret":"RAW-ARGS-MARKER"}',
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
        output_text="RAW-OUTPUT-MARKER",
        error_message=None,
    )


def _compaction_summary_context() -> CompactionSummaryHookContext:
    """Create compaction summary context for tests."""
    return CompactionSummaryHookContext(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
        compaction_id="compact-1",
        reason="manual_command",
        covered_until_event_id="event-1",
        summary="summary",
        continuity_history="RAW-CONTINUITY-MARKER",
    )


def _capture_dispatcher_warnings(monkeypatch: MonkeyPatch) -> list[str]:
    """Capture dispatcher logger warning call message."""
    messages: list[str] = []

    def _spy(msg: str, *args: object, **kwargs: object) -> None:
        del args, kwargs
        messages.append(msg)

    monkeypatch.setattr(dispatcher_module.logger, "warning", _spy)
    return messages


async def test_missing_hook_baseline_noop_records_skipped_trace() -> None:
    """When no hook is registered, leave only skipped trace without call."""
    sink = InMemoryRuntimeHookTraceSink()
    provider = DeterministicRuntimeHookProvider(slug="empty")
    dispatcher = RuntimeHookDispatcher(trace_sink=sink)

    await dispatcher.dispatch_observation(
        [_provider_ref(provider)], "on_run_start", _run_start_context()
    )

    assert provider.calls == []
    assert [(event.provider_slug, event.status) for event in sink.events] == [
        ("empty", "skipped")
    ]


async def test_registration_discovery_calls_only_mapping_entries() -> None:
    """Call only lifecycle registered in hooks() mapping."""
    sink = InMemoryRuntimeHookTraceSink()
    provider = DeterministicRuntimeHookProvider(
        slug="registered",
        actions={"on_run_start": [DeterministicHookAction()]},
    )
    dispatcher = RuntimeHookDispatcher(trace_sink=sink)

    await dispatcher.dispatch_observation(
        [_provider_ref(provider)], "on_run_start", _run_start_context()
    )
    await dispatcher.dispatch_observation(
        [_provider_ref(provider)], "on_run_end", _run_start_context()
    )

    assert [call.lifecycle for call in provider.calls] == ["on_run_start"]
    assert [event.status for event in sink.events] == [
        "started",
        "completed",
        "skipped",
    ]


async def test_provider_ordering_and_turn_prompt_merge() -> None:
    """Call in provider input order and merge prompt results."""
    provider_a = DeterministicRuntimeHookProvider(
        slug="a",
        actions={
            "on_turn_start": [
                DeterministicHookAction(
                    result=TurnStartResult(
                        injected_prompts=[
                            TurnInjectedPrompt(
                                persistence="visible_user_input",
                                text="prompt-a",
                            )
                        ]
                    )
                )
            ]
        },
    )
    provider_b = DeterministicRuntimeHookProvider(
        slug="b",
        actions={
            "on_turn_start": [
                DeterministicHookAction(
                    result=TurnStartResult(
                        injected_prompts=[
                            TurnInjectedPrompt(
                                persistence="hidden_internal_input",
                                text="prompt-b",
                            )
                        ]
                    )
                )
            ]
        },
    )
    dispatcher = RuntimeHookDispatcher(trace_sink=InMemoryRuntimeHookTraceSink())

    result = await dispatcher.dispatch_turn_start(
        [_provider_ref(provider_a), _provider_ref(provider_b)],
        _turn_start_context(),
    )

    assert [call.provider_slug for call in [*provider_a.calls, *provider_b.calls]] == [
        "a",
        "b",
    ]
    assert [prompt.text for prompt in result.injected_prompts] == [
        "prompt-a",
        "prompt-b",
    ]
    assert [prompt.hook_provider_slug for prompt in result.injected_prompts] == [
        "a",
        "b",
    ]
    assert [prompt.hook_prompt_index for prompt in result.injected_prompts] == [0, 0]


async def test_observation_exception_fail_open_and_logs(
    monkeypatch: MonkeyPatch,
) -> None:
    """Observation hook exception is traced/logged, then next provider runs."""
    warning_messages = _capture_dispatcher_warnings(monkeypatch)
    sink = InMemoryRuntimeHookTraceSink()
    failing = DeterministicRuntimeHookProvider(
        slug="failing",
        actions={
            "on_run_start": [DeterministicHookAction(exception=RuntimeError("boom"))]
        },
    )
    next_provider = DeterministicRuntimeHookProvider(
        slug="next",
        actions={"on_run_start": [DeterministicHookAction()]},
    )
    dispatcher = RuntimeHookDispatcher(trace_sink=sink)

    await dispatcher.dispatch_observation(
        [_provider_ref(failing), _provider_ref(next_provider)],
        "on_run_start",
        _run_start_context(),
    )

    assert [call.provider_slug for call in [*failing.calls, *next_provider.calls]] == [
        "failing",
        "next",
    ]
    assert any(event.status == "failed" for event in sink.events)
    assert "Runtime hook failed" in warning_messages


async def test_cancelled_error_propagates() -> None:
    """Hook cancellation propagates instead of fail-open."""
    sink = InMemoryRuntimeHookTraceSink()
    provider = DeterministicRuntimeHookProvider(
        slug="cancel",
        actions={"on_run_start": [DeterministicHookAction(cancelled=True)]},
    )
    dispatcher = RuntimeHookDispatcher(trace_sink=sink)

    try:
        await dispatcher.dispatch_observation(
            [_provider_ref(provider)], "on_run_start", _run_start_context()
        )
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("CancelledError was not propagated")

    assert sink.events[-1].status == "cancelled"


async def test_before_tool_none_allow_and_first_deny_short_circuit() -> None:
    """before hook None means allow, and first deny skips later providers."""
    allow_provider = DeterministicRuntimeHookProvider(
        slug="allow",
        actions={"on_before_tool_call": [DeterministicHookAction(result=None)]},
    )
    deny_provider = DeterministicRuntimeHookProvider(
        slug="deny",
        actions={
            "on_before_tool_call": [
                DeterministicHookAction(
                    result=ToolCallDeny(message="Tool call denied by policy.")
                )
            ]
        },
    )
    skipped_provider = DeterministicRuntimeHookProvider(
        slug="skipped",
        actions={"on_before_tool_call": [DeterministicHookAction()]},
    )
    sink = InMemoryRuntimeHookTraceSink()
    dispatcher = RuntimeHookDispatcher(trace_sink=sink)

    decision = await dispatcher.dispatch_before_tool_call(
        [
            _provider_ref(allow_provider),
            _provider_ref(deny_provider),
            _provider_ref(skipped_provider),
        ],
        _before_context(),
    )

    assert isinstance(decision, ToolCallDeny)
    provider_slugs = [
        call.provider_slug for call in [*allow_provider.calls, *deny_provider.calls]
    ]
    assert provider_slugs == [
        "allow",
        "deny",
    ]
    assert skipped_provider.calls == []
    assert sink.events[-1].short_circuit is True


async def test_before_tool_exception_normalizes_to_allow() -> None:
    """before hook exception fail-opens as allow."""
    provider = DeterministicRuntimeHookProvider(
        slug="failing",
        actions={
            "on_before_tool_call": [
                DeterministicHookAction(exception=RuntimeError("boom"))
            ]
        },
    )
    dispatcher = RuntimeHookDispatcher(trace_sink=InMemoryRuntimeHookTraceSink())

    decision = await dispatcher.dispatch_before_tool_call(
        [_provider_ref(provider)], _before_context()
    )

    assert decision.kind == "allow"


async def test_after_tool_none_unchanged_and_replacement_pipeline() -> None:
    """after hook None means unchanged, and replace_output is reflected as pipeline."""
    unchanged = DeterministicRuntimeHookProvider(
        slug="unchanged",
        actions={"on_after_tool_call": [DeterministicHookAction(result=None)]},
    )
    replace_a = DeterministicRuntimeHookProvider(
        slug="replace-a",
        actions={
            "on_after_tool_call": [
                DeterministicHookAction(result=ToolOutputReplace(output_text="a"))
            ]
        },
    )
    replace_b = DeterministicRuntimeHookProvider(
        slug="replace-b",
        actions={
            "on_after_tool_call": [
                DeterministicHookAction(result=ToolOutputReplace(output_text="b"))
            ]
        },
    )
    dispatcher = RuntimeHookDispatcher(trace_sink=InMemoryRuntimeHookTraceSink())

    decision = await dispatcher.dispatch_after_tool_call(
        [_provider_ref(unchanged), _provider_ref(replace_a), _provider_ref(replace_b)],
        _after_context(),
    )

    assert isinstance(decision, ToolOutputReplace)
    assert decision.output_text == "b"
    assert replace_b.calls[0].context_summary["tool_name"] == "read_file"


async def test_compaction_summary_replacement_pipeline() -> None:
    """Compaction summary hooks receive current summary in provider order."""
    replace_a = DeterministicRuntimeHookProvider(
        slug="replace-a",
        actions={
            "on_compaction_summary": [
                DeterministicHookAction(
                    result=CompactionSummaryReplace(summary="summary-a")
                )
            ]
        },
    )
    replace_b = DeterministicRuntimeHookProvider(
        slug="replace-b",
        actions={
            "on_compaction_summary": [
                DeterministicHookAction(
                    result=CompactionSummaryReplace(summary="summary-b")
                )
            ]
        },
    )
    dispatcher = RuntimeHookDispatcher(trace_sink=InMemoryRuntimeHookTraceSink())

    result = await dispatcher.dispatch_compaction_summary(
        [_provider_ref(replace_a), _provider_ref(replace_b)],
        _compaction_summary_context(),
    )

    assert result == "summary-b"
    assert replace_a.calls[0].context_summary["compaction_id"] == "compact-1"
    assert replace_b.calls[0].context_summary["compaction_id"] == "compact-1"


async def test_compaction_summary_exception_keeps_current_summary() -> None:
    """Compaction summary hook exceptions fail open with current summary."""
    failing = DeterministicRuntimeHookProvider(
        slug="failing",
        actions={
            "on_compaction_summary": [
                DeterministicHookAction(exception=RuntimeError("boom"))
            ]
        },
    )
    replace = DeterministicRuntimeHookProvider(
        slug="replace",
        actions={
            "on_compaction_summary": [
                DeterministicHookAction(
                    result=CompactionSummaryReplace(summary="replacement")
                )
            ]
        },
    )
    dispatcher = RuntimeHookDispatcher(trace_sink=InMemoryRuntimeHookTraceSink())

    result = await dispatcher.dispatch_compaction_summary(
        [_provider_ref(failing), _provider_ref(replace)],
        _compaction_summary_context(),
    )

    assert result == "replacement"


async def test_after_tool_exception_normalizes_to_unchanged() -> None:
    """after hook exception fail-opens as unchanged."""
    provider = DeterministicRuntimeHookProvider(
        slug="failing",
        actions={
            "on_after_tool_call": [
                DeterministicHookAction(exception=RuntimeError("boom"))
            ]
        },
    )
    dispatcher = RuntimeHookDispatcher(trace_sink=InMemoryRuntimeHookTraceSink())

    decision = await dispatcher.dispatch_after_tool_call(
        [_provider_ref(provider)], _after_context()
    )

    assert decision.kind == "unchanged"


async def test_trace_redaction_excludes_raw_markers() -> None:
    """Do not store raw args/output/prompt/credential marker in trace sink."""
    sink = InMemoryRuntimeHookTraceSink()
    provider = DeterministicRuntimeHookProvider(
        slug="redaction",
        actions={"on_after_tool_call": [DeterministicHookAction(result=None)]},
    )
    dispatcher = RuntimeHookDispatcher(trace_sink=sink)

    await dispatcher.dispatch_after_tool_call(
        [_provider_ref(provider)], _after_context()
    )

    assert not sink.contains_marker("RAW-ARGS-MARKER")
    assert not sink.contains_marker("RAW-OUTPUT-MARKER")
    assert not sink.contains_marker("credential-secret-marker")


async def test_trace_sink_exception_fail_open(monkeypatch: MonkeyPatch) -> None:
    """trace sink failure does not block hook dispatch."""
    warning_messages = _capture_dispatcher_warnings(monkeypatch)
    provider = DeterministicRuntimeHookProvider(
        slug="provider",
        actions={"on_run_start": [DeterministicHookAction()]},
    )
    dispatcher = RuntimeHookDispatcher(trace_sink=_FailingTraceSink())

    await dispatcher.dispatch_observation(
        [_provider_ref(provider)], "on_run_start", _run_start_context()
    )

    assert [call.lifecycle for call in provider.calls] == ["on_run_start"]
    assert "Runtime hook trace sink failed" in warning_messages


async def test_hooks_mapping_resolution_failure_skips_provider(
    monkeypatch: MonkeyPatch,
) -> None:
    """General exception from hooks() itself skips that provider."""
    warning_messages = _capture_dispatcher_warnings(monkeypatch)
    sink = InMemoryRuntimeHookTraceSink()
    provider = _HooksFailingProvider(slug="broken")
    dispatcher = RuntimeHookDispatcher(trace_sink=sink)

    await dispatcher.dispatch_observation(
        [_provider_ref(provider)], "on_run_start", _run_start_context()
    )

    assert provider.calls == []
    assert sink.events[0].reason == "hooks_resolution_failed"
    assert "Runtime hooks mapping resolution failed" in warning_messages
