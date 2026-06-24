"""Event assertion helpers.

These helpers verify event streams returned by `live.chat.collect(...)`. They are
small, direct assertions over raw event dicts rather than a separate matcher DSL.
Failure raises `AssertionError(msg)` with enough event type context to debug.

Real-key / dummy-key behavior:
- `run_completed` and `ordered` work with dummy-key runs. Dummy-key runs may emit
  error events but still reach run_complete, which is enough for Phase 3
  feasibility checks.
- `has_text_content` requires a real LLM key. The dummy-key path does not emit
  text_item events.
"""

from typing import Any

from azents.runtime.types import ExecResult


def _types(events: list[dict[str, Any]]) -> list[str]:
    """Return event type fields for compact failure messages."""
    return [str(e.get("type", "<no-type>")) for e in events]


def run_completed(events: list[dict[str, Any]]) -> None:
    """Check that the last event is `run_complete`.

    This works in dummy-key environments because it only verifies completion.
    """
    if not events:
        raise AssertionError("run_completed: empty events")
    last_type = events[-1].get("type")
    if last_type != "run_complete":
        raise AssertionError(
            f"run_completed: last event is {last_type!r}, not 'run_complete'\n"
            f"  types: {_types(events)}",
        )


def has_text_content(events: list[dict[str, Any]]) -> None:
    """Check that a `text_item` event exists and has non-empty content.

    Use this to verify actual LLM text generation. It requires a real LLM key;
    dummy-key environments are expected to fail because they do not emit
    text_item events.
    """
    text_items = [e for e in events if e.get("type") == "text_item"]
    if not text_items:
        raise AssertionError(
            "has_text_content: no text_item event found\n"
            f"  types: {_types(events)}\n"
            "  hint: real LLM API key required (dummy key path has no text_item)",
        )
    for item in text_items:
        # In production-shaped events, `text_item` content lives in the `content` field.
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            return
    raise AssertionError(
        f"has_text_content: text_item(s) present but all empty\n  items: {text_items}",
    )


def ordered(events: list[dict[str, Any]], expected_types: list[str]) -> None:
    """Check that `expected_types` appear in order within the events.

    Example: `ordered(events, ["run_started", "run_complete"])` requires
    run_started before run_complete. Extra events between them are allowed.
    """
    if not expected_types:
        return
    idx = 0
    for event in events:
        if idx >= len(expected_types):
            return
        if event.get("type") == expected_types[idx]:
            idx += 1
    if idx < len(expected_types):
        missing = expected_types[idx:]
        raise AssertionError(
            f"ordered: could not find types in order (missing: {missing})\n"
            f"  expected: {expected_types}\n"
            f"  got:      {_types(events)}",
        )


# ---------------------------------------------------------------------------
# Runtime exec assertions — verify `ExecResult` returned by the Runner operation path.
# ---------------------------------------------------------------------------


def runtime_exec_ok(
    result: ExecResult,
    *,
    stdout_contains: str | None = None,
    stderr_contains: str | None = None,
) -> None:
    """Check that `ExecResult.exit_code == 0` and optional output substrings match.

    Use this for allowed/default shell success verification. When
    `stdout_contains` or `stderr_contains` is provided, each condition must also
    pass.
    """
    if result.exit_code != 0:
        raise AssertionError(
            f"runtime_exec_ok: exit_code={result.exit_code} (expected 0)\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}",
        )
    if stdout_contains is not None and stdout_contains not in result.stdout:
        raise AssertionError(
            f"runtime_exec_ok: stdout does not contain {stdout_contains!r}\n"
            f"  stdout: {result.stdout!r}",
        )
    if stderr_contains is not None and stderr_contains not in result.stderr:
        raise AssertionError(
            f"runtime_exec_ok: stderr does not contain {stderr_contains!r}\n"
            f"  stderr: {result.stderr!r}",
        )


def _function_call_items(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return deduplicated `function_call_item` events.

    The stream can emit the same `id` multiple times, for example an initial
    placeholder with ``output=None`` followed by a final item with output. Keep
    the latest event per id while preserving first-seen order.
    """
    by_id: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []
    for e in events:
        if e.get("type") != "function_call_item":
            continue
        eid = str(e.get("id") or id(e))
        if eid not in by_id:
            ordered_ids.append(eid)
        # Keep the latest event for each id, so output updates replace placeholders.
        by_id[eid] = e
    return [by_id[i] for i in ordered_ids]


def _item_name(event: dict[str, Any]) -> str | None:
    """Return the function name from a function_call_item (`tool_call.name`).

    Engine event schema: ``{"type": "function_call_item", "id", "tool_call":
    {"id", "name", "arguments"}, "output": {"content"} | None}``.
    """
    tool_call = event.get("tool_call")
    if isinstance(tool_call, dict):
        name = tool_call.get("name")
        if isinstance(name, str):
            return name
    return None


def _item_output(event: dict[str, Any]) -> dict[str, Any] | None:
    """Return the final output payload from a function_call_item.

    `output` is a top-level field and may be ``None`` while the stream is still
    in progress. `_function_call_items` deduplicates by id so this returns the
    current latest value.
    """
    output = event.get("output")
    if isinstance(output, dict):
        return output
    return None


def has_function_call(
    events: list[dict[str, Any]],
    *,
    name: str | None = None,
) -> None:
    """Check that at least one `function_call_item` event exists.

    When `name` is provided, require a matching tool call name. This verifies
    that the LLM actually requested a tool call.
    """
    items = _function_call_items(events)
    if not items:
        raise AssertionError(
            f"has_function_call: no function_call_item event found\n  types: {_types(events)}",
        )
    if name is not None:
        matching = [e for e in items if _item_name(e) == name]
        if not matching:
            found_names = [_item_name(e) or "<no-name>" for e in items]
            raise AssertionError(
                f"has_function_call: no function_call_item with name={name!r}\n"
                f"  found names: {found_names}",
            )


def function_call_count(
    events: list[dict[str, Any]],
    *,
    name: str,
    expected: int,
) -> None:
    """Check the number of deduplicated `function_call_item` events for a name.

    Use this to verify agent behavior around repeated calls, including retries.
    """
    count = sum(1 for e in _function_call_items(events) if _item_name(e) == name)
    if count != expected:
        raise AssertionError(
            f"function_call_count: name={name!r} expected={expected} got={count}",
        )


def function_call_succeeded(
    events: list[dict[str, Any]],
    *,
    name: str | None = None,
) -> None:
    """Check that matching `function_call_item.output` payloads are present.

    `output` is a `{content, attachments}`-shaped dict and content must be
    non-empty. This fails when the agent requested a tool but no result object
    was emitted.
    """
    items = _function_call_items(events)
    if name is not None:
        items = [e for e in items if _item_name(e) == name]
    if not items:
        raise AssertionError(
            f"function_call_succeeded: no matching function_call_item\n  types: {_types(events)}",
        )
    for item in items:
        output = _item_output(item)
        if output is None:
            raise AssertionError(
                f"function_call_succeeded: function_call_item has no output\n  event: {item}",
            )
        content = output.get("content")
        if not content:
            raise AssertionError(
                f"function_call_succeeded: output.content is empty\n  output: {output}",
            )


def function_call_output_contains(
    events: list[dict[str, Any]],
    *,
    name: str,
    substring: str,
) -> None:
    """Check that `function_call_item.output.content` contains a substring.

    This verifies text inside a tool result output. If content is not a string
    (for example list[dict]), it is coerced with `str(...)` before substring
    matching.
    """
    matching = [e for e in _function_call_items(events) if _item_name(e) == name]
    if not matching:
        raise AssertionError(
            f"function_call_output_contains: no function_call_item name={name!r}\n"
            f"  types: {_types(events)}",
        )
    for event in matching:
        output = _item_output(event)
        if output is None:
            continue
        content = output.get("content")
        if content is None:
            continue
        if substring in (content if isinstance(content, str) else str(content)):
            return
    raise AssertionError(
        f"function_call_output_contains: name={name!r} has no output.content "
        f"containing {substring!r}\n  matching count: {len(matching)}",
    )


def runtime_exec_blocked(
    result: ExecResult,
    *,
    stderr_contains: str | None = None,
) -> None:
    """Check that runtime execution was blocked (`exit_code != 0`).

    Use this for network blocks, mount escape blocks, and similar deny paths.
    `stderr_contains` can verify the expected block reason, such as "Could not
    resolve" or "Permission denied". `exit_code=-1` timeout also counts as
    blocked.
    """
    if result.exit_code == 0:
        raise AssertionError(
            "runtime_exec_blocked: exit_code=0 "
            "(expected non-zero — command was not blocked)\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}",
        )
    if stderr_contains is not None and stderr_contains not in result.stderr:
        raise AssertionError(
            f"runtime_exec_blocked: stderr does not contain {stderr_contains!r}\n"
            f"  stderr: {result.stderr!r}",
        )
