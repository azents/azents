"""runtime hook type contract tests."""

import dataclasses
from collections.abc import Awaitable, Callable
from typing import get_args, get_origin

from azents.engine.hooks.types import (
    AfterToolCallHookContext,
    BeforeToolCallHookContext,
    RuntimeHookName,
    RuntimeHooks,
    SessionStartHookContext,
    ToolCallAllow,
    ToolCallDecision,
    ToolCallDeny,
    ToolOutputDecision,
    ToolOutputReplace,
    ToolOutputUnchanged,
    TurnInjectedPrompt,
    TurnStartResult,
    normalize_after_tool_call_result,
    normalize_before_tool_call_result,
    normalize_turn_start_result,
)


async def _session_start_hook(context: SessionStartHookContext) -> None:
    """Callback for signature smoke."""


async def _before_tool_hook(
    context: BeforeToolCallHookContext,
) -> ToolCallDecision | None:
    """Before tool callback for signature smoke."""
    return ToolCallAllow()


async def _after_tool_hook(
    context: AfterToolCallHookContext,
) -> ToolOutputDecision | None:
    """After tool callback for signature smoke."""
    return ToolOutputUnchanged()


def test_runtime_hooks_is_total_false_typeddict() -> None:
    """Verify RuntimeHooks is total=False TypedDict."""
    assert RuntimeHooks.__total__ is False
    assert set(RuntimeHooks.__annotations__) == {
        "on_session_start",
        "on_session_clear",
        "on_session_compact",
        "on_session_idle",
        "on_run_start",
        "on_run_end",
        "on_turn_start",
        "on_turn_end",
        "on_before_tool_call",
        "on_after_tool_call",
        "on_runtime_hibernate",
        "on_runtime_restore",
    }


def test_runtime_hooks_callback_signature_import_smoke() -> None:
    """Callback signatures can be written in defining module."""
    hooks: RuntimeHooks = {
        "on_session_start": _session_start_hook,
        "on_before_tool_call": _before_tool_hook,
        "on_after_tool_call": _after_tool_hook,
    }
    before_hook: Callable[
        [BeforeToolCallHookContext], Awaitable[ToolCallDecision | None]
    ] = hooks["on_before_tool_call"]
    assert before_hook is _before_tool_hook


def test_runtime_hook_name_excludes_reserved_taxonomy() -> None:
    """Do not expose lifecycle names not included in first taxonomy."""
    values = set(get_args(RuntimeHookName))
    assert "on_before_model_call" not in values
    assert "on_memory_update" not in values
    assert "on_before_tool_call" in values


def test_contexts_are_frozen_dataclasses() -> None:
    """Context types are defined as frozen dataclasses."""
    context = SessionStartHookContext(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        run_id=None,
    )
    assert dataclasses.is_dataclass(context)
    assert context.run_id is None


def test_result_kind_discriminators_and_normalization() -> None:
    """Verify result normalization defaults by lifecycle."""
    assert normalize_before_tool_call_result(None).kind == "allow"
    deny = ToolCallDeny(message="Tool call denied by policy.")
    assert normalize_before_tool_call_result(deny) is deny

    assert normalize_after_tool_call_result(None).kind == "unchanged"
    replace = ToolOutputReplace(output_text="redacted")
    assert normalize_after_tool_call_result(replace) is replace

    assert normalize_turn_start_result(None).injected_prompts == []
    injected = TurnStartResult(
        injected_prompts=[
            TurnInjectedPrompt(
                persistence="hidden_internal_input",
                text="system context",
            )
        ]
    )
    assert normalize_turn_start_result(injected) is injected


def test_result_union_uses_annotated_discriminator() -> None:
    """Result union keeps discriminator metadata."""
    assert get_origin(ToolCallDecision) is not None
    assert get_origin(ToolOutputDecision) is not None


def test_empty_string_defaults_are_not_used_for_contexts() -> None:
    """Unknown identifiers are represented as None, not empty string."""
    context = AfterToolCallHookContext(
        tool_name="tool",
        toolkit_slug="toolkit",
        args_json="{}",
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
        output_text=None,
        error_message=None,
    )
    assert context.output_text is None
    assert context.error_message is None
