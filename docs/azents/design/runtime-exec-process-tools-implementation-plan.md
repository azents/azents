---
title: "Runtime Exec Process Tools Implementation Plan"
created: 2026-06-27
updated: 2026-06-27
tags: [backend, engine, runtime, toolkit]
---
# Runtime Exec Process Tools Implementation Plan

## Source Documents

- Design: [Runtime Exec Process Tools](./runtime-exec-process-tools.md)
- ADR: [ADR-0081: Runtime Exec Process Tools](../adr/0081-runtime-exec-process.md)

## Scope

This plan breaks the runtime exec process tools feature into reviewable phases. The current delivery goal is **through Phase 1 only**. Later phases are intentionally listed at boundary level so reviewers can validate dependency direction without forcing implementation beyond the current phase.

## Phase Summary

| Phase | Title | Purpose | Base branch | Output branch |
| --- | --- | --- | --- | --- |
| 1 | Generic tool-result metadata | Add the tool-agnostic `FunctionToolResult.metadata: JSONObject` foundation required by exec tools. | `feature/runtime-exec-process-plan` | `feature/runtime-exec-process-phase1` |
| 2 | Runtime process protocol | Add runner/control process operation contracts and result models. | Phase 1 | Future PR |
| 3 | Runner process manager | Implement runner-owned process handles, bounded buffers, stdin write, poll, and cleanup. | Phase 2 | Future PR |
| 4 | Runtime toolkit replacement | Replace `bash` exposure with `exec_command` / `write_stdin` and renderer-owned model text. | Phase 3 | Future PR |
| 5 | UI/live projection and E2E verification | Wire process deltas/projection and run E2E-primary verification matrix. | Phase 4 | Future PR |
| 6 | Spec promotion and cleanup | Promote implemented behavior to living specs and remove temporary plan docs. | Verification | Future PR |

## Requirement Mapping

| Requirement | Phase(s) | Notes |
| --- | --- | --- |
| R1. Replace `bash` with process tools | 4, 5 | Tool exposure and E2E catalog verification happen after protocol/runner support exists. |
| R2. Keep process ownership in Runner | 2, 3, 5 | Protocol models the boundary; runner manager owns handles. |
| R3. Add generic tool-result metadata | 1 | Current phase. No exec-specific engine-core behavior. |
| R4. Stream and buffer output in Runner | 2, 3, 5 | Runner implementation plus live event verification. |
| R5. Enforce bounded process lifecycle | 3, 5 | Runner cleanup policy and missing/expired observations. |
| R6. Keep Phase 1 pipe-based and defer PTY | 2, 3, 4 | Process protocol/schema must not expose `tty` in this series. |
| R7. Keep exec processes separate from background tool calls | 3, 4, 5 | Process tools must not return `BackgroundHandle` for running processes. |

## Phase 1 — Generic Tool-result Metadata

### Covered requirements

- R3. Add generic tool-result metadata

### Purpose

Create the generic metadata carrier required by later exec tool results while keeping engine core tool-agnostic.

### Boundary

Included:

- Add a shared JSON object type for generic metadata.
- Extend `FunctionToolResult` with `metadata: JSONObject = {}`.
- Extend `ClientToolResultPayload` with `metadata: JSONObject = {}` so event transcript/projection can preserve tool metadata.
- Propagate metadata from `FunctionToolResult` through `ToolCatalogClientToolExecutor` into `ClientToolResultPayload`.
- Add unit tests for default metadata, propagation, JSON object validation, and model-visible output stability.

Excluded:

- No `exec_command` or `write_stdin` tools.
- No runtime-control process protocol changes.
- No runner process manager.
- No UI process output projection.
- No `bash` removal yet.
- No PTY/TTY work.

### Input from previous phase

The ADR and design PR define the accepted architecture and requirement IDs. Phase 1 consumes only R3 and must not implement exec-specific logic.

### Output for next phase

Later phases can return `FunctionToolResult(output=..., metadata={...})` from runtime tool handlers and rely on the event transcript carrying that metadata without engine-core exec branches.

### Files and modules likely to change

- `python/apps/azents/src/azents/core/json_types.py` — shared JSON type aliases.
- `python/apps/azents/src/azents/engine/run/types.py` — `FunctionToolResult.metadata`.
- `python/apps/azents/src/azents/engine/events/types.py` — `ClientToolResultPayload.metadata`.
- `python/apps/azents/src/azents/engine/events/tools.py` — metadata propagation from handler result to event payload.
- `python/apps/azents/src/azents/engine/events/tools_test.py` — propagation and output stability tests.
- `python/apps/azents/src/azents/engine/events/types_test.py` — validation tests.

### Interface details

`metadata` must be a JSON object:

```python
type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JSONObject = dict[str, JsonValue]
```

Both `FunctionToolResult.metadata` and `ClientToolResultPayload.metadata` default to `{}`.

Engine/tool execution code may copy or forward metadata but must not interpret exec-specific keys such as `process_id` or `status`.

### Tests

Run at minimum:

```bash
cd python/apps/azents
uv run pytest src/azents/engine/events/tools_test.py src/azents/engine/events/types_test.py
uv run ruff check src/azents/core/json_types.py src/azents/engine/run/types.py src/azents/engine/events/types.py src/azents/engine/events/tools.py src/azents/engine/events/tools_test.py src/azents/engine/events/types_test.py
uv run pyright
```

If full `pyright` is too expensive, run the narrow tests and record why broader CI is delegated to GitHub Actions.

### Completion criteria

- `FunctionToolResult()` callers without metadata keep working.
- Metadata defaults to `{}` and is not shared between instances.
- `FunctionToolResult.metadata` rejects non-object values.
- `ClientToolResultPayload.metadata` rejects non-object values.
- Tool result metadata propagates into client tool result events.
- LiteLLM Responses lowering of `function_call_output.output` remains unchanged by metadata.
- No exec-specific branch or renderer is added to engine core.

## Later Phase Boundaries

### Phase 2 — Runtime process protocol

Define runner/control operations and result dataclasses for process start/write/poll. Keep payloads generation-fenced and pipe-only. Do not implement process handling yet beyond protocol tests/mocks.

### Phase 3 — Runner process manager

Implement runner-local process registry, process states, bounded unread buffers, stdout/stderr drain, stdin write, poll, cleanup, and missing/expired observations.

### Phase 4 — Runtime toolkit replacement

Replace the model-visible runtime shell tool surface with `exec_command` and `write_stdin`. Render model-visible exec result text in the runtime toolkit layer and attach structured metadata through the Phase 1 boundary.

### Phase 5 — UI/live projection and verification

Project process output delta/lifecycle events for UI and run the E2E-primary matrix. Fill the design QA checklist with actual PASS evidence.

### Phase 6 — Spec promotion and cleanup

Update living specs to current implemented behavior, set design `implemented` date, and remove temporary plan documents.

## E2E Primary Verification Matrix

| Scenario | Requirements | Phase verified | Evidence |
| --- | --- | --- | --- |
| Quick command exits through `exec_command` | R1, R3 | 5 | Event transcript and final assistant answer using command output. |
| Long-running command yields and polls | R1, R2, R4, R5 | 5 | `exec_command` returns session id, later empty `write_stdin` returns output and exit. |
| Stdin interaction | R1, R4 | 5 | `write_stdin(chars=...)` changes process output. |
| Missing process observation | R2, R5 | 5 | Controlled runner cleanup/restart yields missing observation. |
| Large output truncation | R4 | 5 | Bounded retained output and truncation metadata/event evidence. |
| `bash` replacement | R1 | 5 | Tool catalog contains `exec_command`/`write_stdin` and omits `bash`. |
| No background completion injection | R7 | 5 | Event transcript shows no background completion injection for process exit. |

## testenv and prerequisite needs

- Live Agent Runtime prerequisite snapshot is required for product E2E.
- testenv support may need helper commands to create deterministic long-running commands and to trigger runner cleanup/restart.
- WebSocket/live event trace capture is required for output delta evidence.
- Phase 1 does not require runtime testenv because it is a generic event/tool-result contract change.

## Blockers and Open Questions

None for Phase 1.

Potential later-phase design checks:

- Exact process id format and cursor naming.
- Whether process live events need a new event kind or only stream projection payloads.
- UI batching/coalescing limits for very large output.
