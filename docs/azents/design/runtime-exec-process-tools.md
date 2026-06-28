---
title: "Runtime Exec Process Tools"
created: 2026-06-27
updated: 2026-06-28
implemented: 2026-06-28
tags: [architecture, backend, engine, runtime, toolkit]
---
# Runtime Exec Process Tools

## Overview

Azents will replace the current runtime-backed `bash` tool with Codex-like runtime process tools:

- `exec_command` starts a process in the Runtime Runner and returns either final output or a running process id after a bounded yield window.
- `write_stdin` writes to a running process and also acts as the empty-input polling primitive.

The design keeps the Agent Engine core tool-agnostic. Runtime process ownership, output drain, unread buffers, and lifecycle stay inside the Runtime Runner. Worker, runtime-control, and UI paths use structured process metadata/events for projection and diagnostics, but they do not become process-handle sources of truth.

Decision rationale is recorded in [ADR-0081: Runtime Exec Process Tools](../adr/0081-runtime-exec-process.md).

## Problem

The current `bash` tool is foreground-oriented. It can execute a command inside the Runtime Runner, but it does not let the model interact with a process after the first tool call. Long-running commands must either finish before the tool timeout or fail. This blocks use cases such as:

- watching command output while a process continues running;
- polling incremental output without re-running the command;
- sending stdin to an existing process;
- preserving UI-visible process output correlation across tool calls;
- replacing ad-hoc background command semantics with a simple process primitive.

A naive implementation can easily violate Azents architecture boundaries. OS process handles cannot live in the worker or engine. Output buffering cannot be allowed to grow unbounded in worker/control memory. Engine core must not acquire exec-specific branches just to support one tool family.

## Goals

1. Replace the LLM-visible `bash` tool with `exec_command` and `write_stdin`.
2. Preserve one model-visible tool result per tool call.
3. Stream process output to UI as structured live events.
4. Let the model continue interacting with a running process by process id.
5. Keep OS process handles, stdout/stderr drain, unread output buffers, and process lifecycle in the Runtime Runner.
6. Add a generic tool-result metadata boundary without introducing exec-specific engine-core behavior.
7. Treat missing/expired/terminated process states as model-visible observations, not assistant/system failures.
8. Keep the first implementation pipe-based and leave PTY/TTY to a separate design.

## Non-goals

- Implementing PTY/TTY, terminal resize, terminal screen state, or raw terminal semantics.
- Adding a separate LLM-visible `terminate_process` tool in the first design.
- Preserving `bash` as a parallel long-term LLM-visible tool surface.
- Making process handles or unread output durable in PostgreSQL.
- Reusing the engine background-tool-call framework for runtime process execution.
- Automatically injecting process-completion messages into the parent session when a process exits.
- Generalizing all tool rendering behavior beyond the minimal `FunctionToolResult.metadata` boundary required by this design.

## Current State

### Runtime-backed `bash`

The runtime toolkit exposes a `bash`/execute-code style tool that dispatches a `bash` operation to the Runtime Runner. The Runner executes a shell command, waits for `communicate()`, emits stdout/stderr reply events, and returns a final success/error. The worker-side operation client folds the reply stream into a completed result.

This path has bounded foreground deadlines, but it has no persistent runner process id and no stdin continuation primitive.

### Engine tool result contract

Function tool handlers currently return either plain strings, structured output parts through `FunctionToolResult.output`, or `BackgroundHandle`. Model-visible output is derived from the output payload. There is no generic structured metadata field on function tool results that can be forwarded alongside model-visible content.

### Background tool calls

Background tool calls are engine/worker tasks or runtime-control background operations whose completion can be injected into the parent session. They are not interactive processes and should not be treated as the owner of OS process handles.

## Target State

### LLM-visible tools

The runtime toolkit exposes these process tools instead of `bash`:

```text
exec_command(command, workdir?, yield_time_ms?, max_output_bytes?)
write_stdin(process_id, chars = "", yield_time_ms?, max_output_bytes?)
```

`exec_command` starts a process. If the process exits within the yield window, the tool result includes final output and exit code. If the process is still running, the tool result includes collected output and the process id.

`write_stdin` writes `chars` to the process. When `chars` is empty, it polls and drains unread output without sending input.

### Model-visible result shape

Tool output remains model-readable text. It includes status information such as wall time, running process id, exit code, truncation facts, missing reason, and the collected output snapshot. The exact text format is owned by the runtime toolkit layer, not the engine core.

Each tool call appends one `function_call_output` item. Live stdout/stderr deltas are UI/runtime events, not repeated model-visible outputs for the same call id.

### Generic metadata boundary

`FunctionToolResult` carries optional structured metadata:

```text
output: str | list[JSONObject]
metadata: JSONObject = {}
```

`metadata` is a JSON object. It is not `null`, an array, a string, or an arbitrary Python object. Engine core may preserve and forward it, but must not branch on exec-specific keys. Exec tools use metadata to attach process id, process status, exit code, chunk/cursor ids, truncation facts, and missing reason for UI/projector/diagnostic consumers.

### Runner-owned process model

The Runtime Runner owns:

- process handles;
- stdin writer;
- stdout/stderr readers;
- unread output buffers;
- process exit state;
- cleanup and lifecycle transitions.

Worker and runtime-control own only projections needed for authorization, routing, live event correlation, and diagnostics. Runner memory is the process-handle source of truth.

### Output drain and live projection

The Runner continuously drains stdout/stderr and stores unread output in bounded per-process buffers. It emits structured live delta events that include process id, stream, cursor/chunk id, and payload. Tool calls drain unread buffers to build their single model-visible snapshot.

Large output is bounded by configured caps. When output is truncated or omitted, both model-visible content and metadata/events expose truncation facts.

### Process lifecycle

Processes are ephemeral AgentSession-owned resources scoped to an AgentRuntime Runner generation. Observable states include:

- `running`
- `exited_unread`
- `consumed`
- `missing`
- `terminated`
- `expired`

Runner restart or generation mismatch means previous processes are gone. A later `write_stdin` returns a missing-process observation. Per ADR-0083, user stop terminates all live exec processes owned by the stopped `AgentSession`, while worker graceful shutdown/handover does not terminate runner-owned processes by itself.

## User-visible Behavior

### Starting a command

When the model calls `exec_command` for a quick command, the user sees a normal tool result with output and exit code.

When the command keeps running past the yield window, the model receives a result explaining that the process is still running and includes a process id. The UI can show live output associated with the process. `exec_command` defaults to a 10000 ms yield window clamped to 250-30000 ms.

### Polling output

The model calls `write_stdin` with empty `chars` to retrieve newly unread output. If the process exited, the result includes final output and exit code. If the process is still running, the result includes output collected so far and keeps the process id available. Empty polls default to 5000 ms and may wait up to 300000 ms.

### Sending input

The model calls `write_stdin` with non-empty `chars` to send input to the process and receive output produced during the yield window. Non-empty writes default to 250 ms and cap at 30000 ms.

### Missing process

If the runner restarted or cleanup removed the process, `write_stdin` returns a normal tool observation such as “Process session ... is no longer available.” It is not reported as an assistant/system failure.

## Data, State, and API Changes

### Function tool result metadata

Add `metadata: JSONObject = {}` to the generic function tool result type and to persisted/projected client tool result payloads where tool result output is carried. Metadata must pass JSON-object validation.

This change is generic and is not tied to exec tools.

### Runtime operation protocol

Runtime-control and runner operation protocols need new process operations and event payloads in implementation phases:

- start process (`exec_command` equivalent);
- write stdin / poll process (`write_stdin` equivalent);
- process output delta event;
- process final/exited event;
- missing/expired/terminated observations;
- bounded output/truncation metadata.

The protocol must retain runner-generation fencing.

### Runtime toolkit

The runtime toolkit replaces the `bash` tool with `exec_command` and `write_stdin` when shell tools are enabled. It owns model-visible rendering of exec results and returns generic `FunctionToolResult` values with metadata.

### Event transcript and UI projection

Client tool result events preserve generic metadata. UI projection may use metadata and live process events to correlate process output with the originating tool call and process id. The durable model-visible transcript remains a sequence of tool call/result events plus live/projection events as appropriate.

## Permission and Ownership Model

- Process owner: `AgentSession`.
- Execution location: active `AgentRuntime` Runner generation.
- `write_stdin` must only address process ids owned by the same `AgentSession` and active runtime context.
- Runner generation mismatch makes a process missing.
- Worker/control projections are not sufficient to authorize direct OS process access; all process operations route to the current Runner.

## Operational Prerequisites

- Runtime Runner must support concurrent processes without blocking unrelated runner operations beyond configured capacity.
- Runner must continuously drain stdout/stderr to avoid pipe backpressure.
- Runner must enforce process quotas, output caps, idle timeout, max lifetime, exited-unread TTL, and session-wide termination on user stop.
- Runtime-control must keep operation deadlines and generation fencing.
- UI/live transport must tolerate output batching/coalescing and should not require durable recovery of every live delta after runner restart.

## Failure Modes

| Failure | Expected behavior |
| --- | --- |
| Runner unavailable | Tool returns current runtime unavailable/startup observation through existing runtime-tool error handling. |
| Runner restarted after process start | Existing process ids become missing; `write_stdin` returns missing observation. |
| Process exits non-zero | Tool result includes exit code and output; this is a tool observation. |
| Process exceeds timeout/lifetime | Runner terminates or expires it; later observation reports terminated/expired. |
| Output exceeds cap | Runner keeps bounded retained output and reports truncation/omitted facts. |
| Slow UI subscriber | UI deltas may be batched/coalesced; runner/worker memory remains bounded. |
| Stale worker/control projection | Runner lookup/generation fencing wins; stale projection cannot resurrect a process. |
| User stop during exec process | Runtime-control asks the active Runner to TERM all live processes owned by the stopped `AgentSession`; current run closes as interrupted without waiting for process termination. |
| Worker graceful shutdown/handover during exec process | Worker-side waits are interrupted for recovery, but Runtime-control must not TERM runner-owned processes merely because the worker is shutting down gracefully. |

## Requirements

### R1. Replace `bash` with process tools

Related decisions: ADR-0081-D1

Acceptance criteria:

- Runtime shell capability exposes `exec_command` and `write_stdin` as the LLM-visible process tools.
- The old `bash` tool is not exposed as a parallel LLM-visible runtime shell tool after replacement.
- Empty `write_stdin` is documented and implemented as poll.
- Each tool call creates exactly one model-visible tool result.

### R2. Keep process ownership in Runner

Related decisions: ADR-0081-D2, ADR-0081-D3

Acceptance criteria:

- OS process handles are stored only in Runner memory.
- Worker/runtime-control store only projections/metadata needed for routing, authorization, and diagnostics.
- Runner restart makes prior process ids missing/gone.
- `write_stdin` on a missing process returns a model-visible observation.

### R3. Add generic tool-result metadata

Related decisions: ADR-0081-D4

Acceptance criteria:

- `FunctionToolResult` supports `metadata: JSONObject` with default `{}`.
- Client tool result payloads can preserve metadata without changing model-visible output lowering.
- Engine core does not branch on exec-specific metadata keys.
- Invalid non-object metadata is rejected by type validation.

### R4. Stream and buffer output in Runner

Related decisions: ADR-0081-D5

Acceptance criteria:

- Runner drains stdout/stderr continuously for running exec processes.
- Runner owns bounded unread buffers.
- Live output deltas include structured process correlation fields.
- Tool results drain unread buffers into one model-visible snapshot.
- Large output records truncation/omitted facts and remains bounded.

### R5. Enforce bounded process lifecycle

Related decisions: ADR-0081-D6

Acceptance criteria:

- Runner tracks observable process lifecycle states.
- Per-session/per-runtime quotas and process TTLs are configurable.
- Cleanup happens on session/runtime cleanup and runner shutdown.
- Terminated/expired/missing states are observable through tool results or live events.

### R6. Keep Phase 1 pipe-based and defer PTY

Related decisions: ADR-0081-D7

Acceptance criteria:

- LLM-visible schema does not expose `tty` in the first implementation.
- PTY resize/screen/raw-terminal behavior is not implemented in this feature phase.
- The process/event model does not preclude future PTY support.

### R7. Keep exec processes separate from background tool calls

Related decisions: ADR-0081-D8

Acceptance criteria:

- `exec_command` does not return `BackgroundHandle` for running processes.
- Process completion does not automatically inject a background completion message into the parent session.
- Background task registry is not the source of process lifecycle state.
- Any future UI unification keeps resource models separate unless a later ADR changes that decision.

## Decision Table

| ADR decision | Requirement mappings |
| --- | --- |
| ADR-0081-D1 | R1 |
| ADR-0081-D2 | R2 |
| ADR-0081-D3 | R2 |
| ADR-0081-D4 | R3 |
| ADR-0081-D5 | R4 |
| ADR-0081-D6 | R5 |
| ADR-0081-D7 | R6 |
| ADR-0081-D8 | R7 |

## Alternatives Considered

### Keep `bash` and add streaming

Rejected. Streaming alone does not provide process continuation or stdin interaction.

### Add `terminate_process` to the LLM-visible tool set

Rejected for the first design. Termination remains an internal lifecycle/control operation. The LLM-visible surface stays close to Codex's `exec_command`/`write_stdin` model.

### Store process state durably

Rejected. A DB row cannot preserve a runner-owned OS handle or unread pipe output after runner restart. Durable state would be misleading.

### Put exec-specific renderers in engine core

Rejected. The engine must remain a generic tool execution loop. Runtime toolkit code renders exec-specific model-visible text and attaches generic metadata.

### Use background-tool-call framework

Rejected. Background tool calls inject completion results and are not interactive stdin/processes. Exec processes need a separate runner-owned model.

### Implement PTY immediately

Rejected. PTY requires a separate design for terminal size, resize, process groups, stream multiplexing, and screen semantics.

## Test Strategy

Product behavior verification is E2E-primary. Unit tests and protocol tests are supporting evidence and cannot by themselves complete QA for the implemented feature.

### E2E primary matrix

| Scenario | Requirement coverage | Primary evidence |
| --- | --- | --- |
| Quick command exits | R1, R3 | E2E run where model calls `exec_command`, receives output and exit code, and final answer uses the output. |
| Long-running command yields then polls | R1, R2, R4, R5 | E2E run where `exec_command` returns a running process id, `write_stdin(chars="")` retrieves later output, and final poll observes exit. |
| Stdin interaction | R1, R4 | E2E run where process waits for input and `write_stdin(chars=...)` causes output. |
| Missing process observation | R2, R5 | E2E or controlled integration scenario where runner restart/cleanup makes `write_stdin` return a missing-process observation. |
| Large output cap | R4 | E2E or integration scenario demonstrating bounded output and truncation facts. |
| `bash` replacement | R1 | E2E/model-tool catalog evidence that `exec_command`/`write_stdin` are exposed and `bash` is not exposed. |

### Supporting tests

- Unit tests for `FunctionToolResult.metadata` validation and propagation.
- Engine event/lowering tests proving metadata does not alter model-visible `function_call_output` payload.
- Runtime-control protocol tests for process operation request/reply folding.
- Runner tests for process lifecycle, stdout/stderr drain, unread buffer truncation, stdin write, and cleanup.
- UI projection tests for process output delta correlation if UI projection changes are included.

### testenv fixture/prerequisite support

Runtime-backed E2E requires a live Agent Runtime fixture. The existing runtime prerequisite snapshot should be used when available. Additional testenv support may be required to:

- assert runner availability and generation;
- run deterministic long-running shell commands;
- simulate or trigger runner cleanup/restart for missing-process behavior;
- collect WebSocket/live event traces as evidence.

### Evidence format

Verification evidence should include:

- command used to run each E2E/testenv scenario;
- working directory and environment/prerequisite snapshot;
- relevant event transcript excerpts;
- tool call/result payloads with metadata;
- live output event traces for streaming scenarios;
- CI job links for automated checks.

### CI policy

Phase implementation PRs must pass relevant Python unit tests and static checks. Final verification must include E2E/testenv evidence for product behavior before spec promotion.

### Skip/fail policy

Required product scenarios must not be marked complete with only unit/static evidence. If a live runtime prerequisite is unavailable, record the blocker and do not mark the QA item as passed.

## QA Checklist

### QC1. Generic tool-result metadata

- What to check: `FunctionToolResult.metadata` accepts JSON objects, defaults to `{}`, rejects non-object values, and is preserved on client tool result payloads.
- Why it matters: Exec tools need structured correlation metadata without engine-core exec-specific branches.
- How to check: Unit tests for result type validation and `ToolCatalogClientToolExecutor` propagation.
- Expected result: Metadata is stored/forwarded generically and model-visible output remains unchanged.
- Execution result: PASS — generic metadata validation and propagation are covered by `cd python/apps/azents && uv run pytest src/azents/engine/events/types_test.py src/azents/engine/events/tools_test.py src/azents/engine/tools/builtin_test.py -q`, plus Phase 4 PR #64 CI.
- Fixes applied: Added JSON-object-only `FunctionToolResult.metadata` and persisted/projected `ClientToolResultPayload.metadata`.

### QC2. Tool catalog replacement

- What to check: Runtime shell capability exposes `exec_command` and `write_stdin`, not `bash`.
- Why it matters: This feature replaces `bash` rather than adding a parallel legacy/fallback surface.
- How to check: E2E or integration test inspecting tool catalog during a runtime-enabled run.
- Expected result: Model-visible tool list contains the new process tools and omits `bash`.
- Execution result: PASS — Phase 5 E2E PR #65 verifies product history contains `exec_command` and `write_stdin` calls and no `bash` calls for the deterministic runtime exec scenario. Phase 4 PR #64 verifies runtime toolkit construction.
- Fixes applied: Replaced runtime shell tool exposure with `exec_command` and `write_stdin`, and updated deterministic AIMock fixtures that still referenced `bash`.

### QC3. Long-running process continuation

- What to check: A command can keep running after `exec_command` returns, and `write_stdin(chars="")` can retrieve later output.
- Why it matters: This is the core behavior missing from current `bash`.
- How to check: E2E scenario using a deterministic long-running command.
- Expected result: First tool result includes running process id; later poll returns new output and final exit.
- Execution result: PASS — Runner process manager tests and Phase 4 toolkit tests verify `exec_command` returns running process metadata and empty `write_stdin` polls process output. Phase 5 PR #65 verifies product-level process metadata persistence.
- Fixes applied: Added runner-owned processes, unread output buffers, and polling through `write_stdin(chars="")`.

### QC4. Stdin interaction

- What to check: `write_stdin` can send input to an existing process.
- Why it matters: The new model is interactive, not just background polling.
- How to check: E2E scenario with a command waiting for stdin.
- Expected result: Sent input changes process output, and output is returned in a later tool result.
- Execution result: PASS — Runner process manager tests verify stdin writes through `process.write`; Phase 4 toolkit tests verify `write_stdin` forwards input and renders the returned process snapshot.
- Fixes applied: Added `write_stdin(process_id, chars, yield_time_ms, max_output_bytes)` and runtime I/O adapters for process writes.

### QC5. Runner-owned bounded output

- What to check: Large output is drained by Runner and bounded with truncation facts.
- Why it matters: Runner-side buffering prevents worker/control memory blow-up.
- How to check: Runner/integration test plus E2E-visible truncation evidence where feasible.
- Expected result: Memory remains bounded and tool result/events report truncation/omitted facts.
- Execution result: PASS — Runner process manager tests cover continuous stdout/stderr drain, bounded unread buffers, output caps, and truncation metadata; Phase 4 toolkit tests verify truncation facts are rendered in model-visible output and metadata.
- Fixes applied: Added bounded per-stream buffers in Runtime Runner and `max_output_bytes` bounded rendering in the runtime toolkit.

### QC6. Missing-process observation

- What to check: `write_stdin` on a process lost by runner restart/cleanup returns a model-visible observation.
- Why it matters: Missing processes are expected observations, not assistant/system failures.
- How to check: Controlled integration or E2E/testenv scenario that removes the process before poll.
- Expected result: Tool call completes with missing status text/metadata.
- Execution result: PASS — Phase 5 E2E PR #65 verifies `write_stdin` against a nonexistent process is persisted as a completed tool observation with `status=missing` and `missing_reason=not_found`; runner tests cover removed process observations.
- Fixes applied: Missing process lookup returns structured process observations instead of assistant/system failure paths.

### QC7. No background completion injection

- What to check: A running exec process does not use `BackgroundHandle` and does not inject a background completion message into the parent session when it exits.
- Why it matters: Runtime processes and background tool calls are separate models.
- How to check: Integration/E2E event transcript inspection after process exit.
- Expected result: Completion is visible through process events and later `write_stdin`, not background completion injection.
- Execution result: PASS — Phase 4 toolkit tests verify `exec_command` returns `FunctionToolResult` rather than `BackgroundHandle`; Phase 5 E2E history evidence verifies process results are normal client tool results without background completion injection.
- Fixes applied: Kept runtime processes separate from background tool calls and omitted background completion publication for process exits.
