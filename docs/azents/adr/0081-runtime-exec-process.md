---
title: "ADR-0081: Runtime Exec Process Tools"
created: 2026-06-27
tags: [architecture, backend, engine, runtime, toolkit]
---
# ADR-0081: Runtime Exec Process Tools

## Context

Azents currently exposes a runtime-backed `bash` tool whose runner implementation behaves like a bounded foreground command: the runner executes a shell process, collects stdout/stderr, and returns one final tool result. The runtime coordination path already has stdout/stderr reply event types, but current bash execution does not model a live process that the agent can continue to poll or write to after the first tool call.

Codex's exec design uses a small process-oriented tool surface: `exec_command` starts a process and returns either an exit result or a running session id after a yield window; `write_stdin` writes to that session and also acts as an empty-input poll. Intermediate stdout/stderr is streamed as live events, not as repeated `function_call_output` items for the same tool call.

Azents needs a similar model to replace `bash` while preserving Azents boundaries:

- Agent Engine core must remain tool-agnostic.
- Runtime Runner is the only component that can own OS process handles.
- Runner is an external component; server/runtime lifecycle must not be inferred from runner process signals alone.
- Tool errors, missing processes, and process exits are observations returned to the model, not assistant/system failures.
- Live UI output needs structured process ids and event metadata.

## Decision

### ADR-0081-D1. Replace `bash` with `exec_command` and `write_stdin`

Azents will replace the LLM-visible `bash` tool with two process tools:

- `exec_command` starts a runtime process and waits up to `yield_time_ms` for output.
- `write_stdin` writes bytes/text to an existing process session and waits up to `yield_time_ms` for output.

`write_stdin` with empty input is the polling primitive. The first implementation does not expose a separate LLM-visible `terminate_process` tool. Termination remains available through runner/control cleanup, user stop, runtime shutdown, quota pruning, and future internal/client APIs.

Each LLM tool call still produces at most one model-visible tool result. Intermediate process output is emitted as live process events, not as repeated `function_call_output` for the same call id.

### ADR-0081-D2. Runtime process handles are runner-owned

The Runtime Runner owns process handles, stdin writers, stdout/stderr readers, process exit state, and unread output buffers. Worker, engine, and runtime-control components keep only structured projections for authorization, routing, live event correlation, diagnostics, and missing-process observations.

A process is owned by an `AgentSession` and executes inside that session's selected `AgentRuntime` Runner generation. Follow-up `write_stdin` calls are valid only for processes owned by the same `AgentSession`.

### ADR-0081-D3. Process state is runner-memory only and ephemeral

Exec processes are ephemeral runner-local resources. Azents does not add a DB-backed durable process registry for process handles or unread output. The runner is the parent process for child exec processes; when the runner exits or restarts, its child processes must be considered gone.

Worker/runtime-control projections are best-effort live metadata, not a source of truth. If a projected process no longer exists in the active runner generation, a follow-up `write_stdin` returns a model-visible missing-process observation.

### ADR-0081-D4. Add generic `FunctionToolResult.metadata` as a JSON object

Engine core must not introduce exec-specific result types, branches, or renderers. Instead, Azents extends the generic function tool result contract with optional structured metadata:

- `output`: existing model-visible tool result payload (`str` or content part list).
- `metadata`: a JSON object (`JSONObject`) with default `{}`.

The engine core may store and forward metadata but must not interpret exec-specific keys. `exec_command` and `write_stdin` render their model-visible output in the runtime toolkit layer and attach structured metadata such as process id, status, exit code, chunk id, truncation facts, and missing reason.

### ADR-0081-D5. Runner-owned output uses bounded unread buffers and live deltas

The runner continuously drains stdout/stderr for every exec process. It owns per-process bounded unread output buffers and emits structured live output delta events for UI projection. `exec_command` and `write_stdin` drain unread buffers to build their single tool result snapshot.

Output buffering is bounded. Large output must not grow unbounded in runner or worker memory. The runner records truncation facts such as retained bytes, omitted bytes, and stream cap reach. Worker/runtime-control project deltas and metadata but do not become the output source of truth.

### ADR-0081-D6. Exec process lifecycle is bounded

The process lifecycle includes at least these observable states:

- `running`
- `exited_unread`
- `consumed`
- `missing`
- `terminated`
- `expired`

The system enforces configurable per-session and per-runtime process quotas, unread output caps, idle timeout, max lifetime, and exited-unread TTL. Cleanup triggers include process exit after final output consumption, exited-unread TTL expiry, idle timeout, max lifetime expiry, AgentSession cleanup, AgentRuntime stop/replacement, runner shutdown, and quota pruning.

Missing, expired, terminated, and non-zero exit states are returned to the model as tool observations where possible.

### ADR-0081-D7. Initial implementation is pipe-based; PTY is deferred

The first implementation is pipe-based. It does not expose `tty` in the LLM-visible schema and does not implement terminal resize, terminal screen state, or PTY-specific raw terminal semantics.

The process/event model must remain compatible with future PTY support, including terminal-sized sessions and raw terminal output. PTY requires a separate design pass.

### ADR-0081-D8. Exec processes are separate from engine background tool calls

`exec_command` and `write_stdin` use the runner-owned process model, not the existing `BackgroundHandle`/background-tool-call framework. A running process is resumed through `write_stdin` by process/session id and does not inject an automatic completion message into the parent session when it exits.

Completion, output deltas, and missing/expired states are process lifecycle events and become model-visible only when a later tool call observes them. Background tasks and runtime processes may share UI concepts later, and the background-tool-call framework may be reconsidered in a future design, but this ADR keeps them separate.

## Consequences

### Positive

- Long-running shell commands no longer block the agent until process exit.
- The LLM receives a Codex-like process primitive while Azents preserves runner ownership boundaries.
- Runner-side buffering reduces the chance that worker/control memory grows with unbounded command output.
- UI streaming can correlate deltas, stdin interactions, and exits by structured process id.
- Engine core remains tool-agnostic; exec-specific rendering stays in the runtime toolkit layer.
- Runner restart semantics are clear: runner-local processes are ephemeral and become missing/gone.

### Negative / trade-offs

- `bash` compatibility is intentionally not preserved as a parallel tool surface.
- No LLM-visible terminate tool means explicit stop relies on user stop/cleanup or input-based interruption until a future design changes the tool set.
- Runner protocol and implementation become more complex because runner owns process buffers and lifecycle.
- Missing process observations are expected after runner restart; final unread output may be lost.
- PTY/TTY is deferred, so REPL-like terminal behavior remains limited in the first phase.

## Alternatives

### Keep `bash` and add streaming only

Rejected. Incremental stdout/stderr streaming improves UI responsiveness but does not solve long-running process continuation, stdin interaction, or polling after a yield window.

### Add `exec_command`, `write_stdin`, and `terminate_process` as LLM tools

Rejected for the first design. Codex's minimal LLM-visible process surface uses `exec_command` and `write_stdin`; empty `write_stdin` is the polling primitive. Termination remains an internal lifecycle/control concern for now.

### Make worker/control the process output source of truth

Rejected. The runner owns the OS process and must continuously drain output to avoid pipe backpressure and memory hazards. Keeping unread buffers in worker/control would split source of truth from process ownership and increase memory risk outside the runner.

### Store process handles/state durably in PostgreSQL

Rejected. Process handles and unread output cannot be recovered from DB after runner restart. A durable registry would create a false sense of recoverability and add drift between DB state and runner memory.

### Add exec-specific result handling to engine core

Rejected. Engine core must stay tool-agnostic. Generic `FunctionToolResult.metadata` is the boundary; exec rendering is owned by the runtime toolkit layer.

### Implement PTY in the first phase

Rejected. PTY introduces terminal resize, multiplexed stdout/stderr, ANSI/control sequence rendering, process group, and terminal screen semantics. It is useful but deserves a separate design.

### Implement exec processes using the background-tool-call framework

Rejected. Background tool calls are worker-local or control-published tasks with completion injection. Runtime exec processes are runner-owned interactive resources resumed by `write_stdin`. They should remain separate models.

## Related documents

- [ADR-0010: Background Tool Call Design Discussion](./0010-background-tool-call.md)
- [Background Tool Call Design](../design/background-tool-call.md)
- [Agent Runtime Control Spec](../spec/flow/agent-runtime-control.md)
- [Agent Execution Loop Spec](../spec/flow/agent-execution-loop.md)
