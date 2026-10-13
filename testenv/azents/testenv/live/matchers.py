"""Assertions over typed public Chat actions and Runner results."""

from dataclasses import dataclass

from azents.runtime.types import ExecResult

from .events import (
    AssistantPayload,
    ChatAction,
    ToolCallPayload,
    ToolResultPayload,
    content_text,
    event_name,
    terminal_run,
)


def _types(events: list[ChatAction]) -> list[str]:
    """Return canonical event names for compact failure messages."""
    return [event_name(event) for event in events]


def run_completed(events: list[ChatAction]) -> None:
    """Require a terminal durable run marker, including failed dummy-key runs."""
    if not events or not terminal_run(events[-1]):
        raise AssertionError(
            f"run_completed: last action is not a terminal run marker: {_types(events)}"
        )


def has_text_content(events: list[ChatAction]) -> None:
    """Require non-empty assistant text, including canonical structured text parts."""
    for action in events:
        event = action.event
        if event is not None and isinstance(event.payload, AssistantPayload):
            if content_text(event.payload.content).strip():
                return
    raise AssertionError(f"has_text_content: no non-empty assistant message: {_types(events)}")


def ordered(events: list[ChatAction], expected_types: list[str]) -> None:
    """Require canonical event/action names in order, allowing intervening actions."""
    index = 0
    for action in events:
        if index == len(expected_types):
            return
        if event_name(action) == expected_types[index]:
            index += 1
    if index != len(expected_types):
        raise AssertionError(f"ordered: missing {expected_types[index:]}; got {_types(events)}")


@dataclass(frozen=True)
class _ToolCall:
    """Latest call and result observations correlated by canonical call_id."""

    call: ToolCallPayload
    result: ToolResultPayload | None


def _function_call_items(events: list[ChatAction]) -> list[_ToolCall]:
    """Correlate canonical client calls/results; deduplicate live/history copies."""
    calls: dict[str, ToolCallPayload] = {}
    results: dict[str, ToolResultPayload] = {}
    for action in events:
        if action.event is None:
            continue
        payload = action.event.payload
        if isinstance(payload, ToolCallPayload):
            calls[payload.call_id] = payload
        elif isinstance(payload, ToolResultPayload):
            results[payload.call_id] = payload
    return [_ToolCall(call=call, result=results.get(call_id)) for call_id, call in calls.items()]


def has_function_call(events: list[ChatAction], *, name: str | None = None) -> None:
    """Require a canonical client-tool call, optionally with the selected name."""
    items = _function_call_items(events)
    if not any(name is None or item.call.name == name for item in items):
        raise AssertionError(f"has_function_call: no matching client tool call: {_types(events)}")


def function_call_count(events: list[ChatAction], *, name: str, expected: int) -> None:
    """Check the count of unique canonical tool-call identities."""
    count = sum(item.call.name == name for item in _function_call_items(events))
    if count != expected:
        raise AssertionError(f"function_call_count: name={name!r} expected={expected} got={count}")


def function_call_succeeded(events: list[ChatAction], *, name: str | None = None) -> None:
    """Require completed matching results with non-empty canonical output."""
    items = [
        item for item in _function_call_items(events) if name is None or item.call.name == name
    ]
    if not items:
        raise AssertionError("function_call_succeeded: no matching client tool call")
    for item in items:
        if item.result is None or item.result.status != "completed" or not item.result.output:
            raise AssertionError(
                f"function_call_succeeded: no successful output for {item.call.call_id}"
            )


def function_call_output_contains(events: list[ChatAction], *, name: str, substring: str) -> None:
    """Require text in a correlated result; rich artifact payloads stay opaque."""
    for item in _function_call_items(events):
        if item.call.name == name and item.result is not None:
            if substring in content_text(item.result.output):
                return
    raise AssertionError(
        f"function_call_output_contains: {name!r} has no output containing {substring!r}"
    )


def runtime_exec_ok(
    result: ExecResult,
    *,
    stdout_contains: str | None = None,
    stderr_contains: str | None = None,
) -> None:
    """Check a successful Runner execution and optional output substrings."""
    if result.exit_code != 0:
        raise AssertionError(f"runtime_exec_ok: exit_code={result.exit_code} (expected 0)")
    if stdout_contains is not None and stdout_contains not in result.stdout:
        raise AssertionError(f"runtime_exec_ok: stdout does not contain {stdout_contains!r}")
    if stderr_contains is not None and stderr_contains not in result.stderr:
        raise AssertionError(f"runtime_exec_ok: stderr does not contain {stderr_contains!r}")


def runtime_exec_blocked(result: ExecResult, *, stderr_contains: str | None = None) -> None:
    """Check a blocked Runner execution and optional diagnostic substring."""
    if result.exit_code == 0:
        raise AssertionError("runtime_exec_blocked: exit_code=0 (expected non-zero)")
    if stderr_contains is not None and stderr_contains not in result.stderr:
        raise AssertionError(f"runtime_exec_blocked: stderr does not contain {stderr_contains!r}")
